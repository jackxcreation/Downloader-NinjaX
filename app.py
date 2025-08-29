import os
import re
import json
import time
import uuid
import hashlib
import logging
import asyncio
import smtplib
import threading
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request, jsonify, send_file, abort, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
import yt_dlp
import instaloader
import requests
from bs4 import BeautifulSoup
import validators

# Configure comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app with proper configuration
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Enhanced Configuration
app.config.update({
    'SECRET_KEY': os.environ.get('SECRET_KEY', str(uuid.uuid4())),
    'MAX_CONTENT_LENGTH': 500 * 1024 * 1024,  # 500MB max
    'DOWNLOAD_FOLDER': os.path.join(os.getcwd(), 'downloads'),
    'TEMP_FOLDER': os.path.join(os.getcwd(), 'temp'),
    'STATIC_FOLDER': os.path.join(os.getcwd(), 'static'),
    'UPLOAD_FOLDER': os.path.join(os.getcwd(), 'uploads'),
    
    # Email Configuration
    'SMTP_SERVER': os.environ.get('SMTP_SERVER', 'smtp.gmail.com'),
    'SMTP_PORT': int(os.environ.get('SMTP_PORT', 587)),
    'EMAIL_USER': os.environ.get('EMAIL_USER', 'jodjack64@gmail.com'),
    'EMAIL_PASS': os.environ.get('EMAIL_PASS', ''),
    
    # API Configuration
    'API_RATE_LIMIT': os.environ.get('API_RATE_LIMIT', '50 per minute'),
    'DOWNLOAD_RATE_LIMIT': os.environ.get('DOWNLOAD_RATE_LIMIT', '10 per minute'),
    
    # Security Configuration
    'CSRF_ENABLED': True,
    'WTF_CSRF_TIME_LIMIT': None,
    'SESSION_COOKIE_SECURE': True,
    'SESSION_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_SAMESITE': 'Lax',
})

# Create all necessary directories
for folder in ['DOWNLOAD_FOLDER', 'TEMP_FOLDER', 'STATIC_FOLDER', 'UPLOAD_FOLDER']:
    folder_path = app.config[folder]
    os.makedirs(folder_path, exist_ok=True)
    logger.info(f"Created/verified directory: {folder_path}")

# Enhanced CORS configuration
CORS(app, 
     origins=['*'], 
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization', 'X-Requested-With'],
     supports_credentials=True)

# Enhanced Rate limiting with Redis fallback
try:
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["1000 per hour", "100 per minute"],
        storage_uri=os.environ.get('REDIS_URL', 'memory://')
    )
    logger.info("Rate limiter initialized with Redis/Memory backend")
except Exception as e:
    logger.warning(f"Rate limiter initialization failed: {e}")
    limiter = None

# Thread pool for background tasks
executor = ThreadPoolExecutor(max_workers=20)

class SecurityValidator:
    """Enhanced Security validation for URLs and inputs"""
    
    BLOCKED_DOMAINS = [
        'localhost', '127.0.0.1', '0.0.0.0', '::1',
        'internal', 'private', 'admin', '10.', '192.168.', '172.'
    ]
    
    BLOCKED_EXTENSIONS = [
        '.exe', '.bat', '.cmd', '.com', '.pif', '.scr', '.vbs', '.js'
    ]
    
    MAX_URL_LENGTH = 2048
    MAX_FILENAME_LENGTH = 255

    @staticmethod
    def validate_url(url):
        """Comprehensive URL validation"""
        if not url or len(url) > SecurityValidator.MAX_URL_LENGTH:
            return False, "URL too long or empty"
        
        if not validators.url(url):
            return False, "Invalid URL format"

        try:
            parsed = urlparse(url)
            
            # Check for blocked domains
            if any(blocked in parsed.netloc.lower() for blocked in SecurityValidator.BLOCKED_DOMAINS):
                return False, "Access to this domain is not allowed"

            # Check for suspicious patterns
            if re.search(r'[<>"\'\\]|javascript:|data:|vbscript:', url.lower()):
                return False, "URL contains invalid or potentially malicious characters"
            
            # Validate scheme
            if parsed.scheme not in ['http', 'https']:
                return False, "Only HTTP and HTTPS URLs are allowed"
            
            return True, "Valid URL"
            
        except Exception as e:
            return False, f"URL validation error: {str(e)}"

    @staticmethod
    def sanitize_filename(filename):
        """Enhanced filename sanitization"""
        if not filename:
            return f"download_{int(time.time())}"
        
        # Remove path components
        filename = os.path.basename(filename)
        
        # Secure filename
        filename = secure_filename(filename)
        
        # Additional sanitization
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
        filename = filename.strip('. ')
        
        # Limit length
        if len(filename) > SecurityValidator.MAX_FILENAME_LENGTH:
            name, ext = os.path.splitext(filename)
            filename = name[:SecurityValidator.MAX_FILENAME_LENGTH-len(ext)-10] + ext
        
        # Ensure it's not empty
        if not filename:
            filename = f"download_{int(time.time())}"
            
        return filename

    @staticmethod
    def validate_file_extension(filename):
        """Validate file extension"""
        ext = os.path.splitext(filename.lower())[1]
        return ext not in SecurityValidator.BLOCKED_EXTENSIONS

class YouTubeDownloader:
    """Enhanced YouTube video downloader with comprehensive features"""
    
    def __init__(self):
        self.ydl_opts_base = {
            'quiet': True,
            'no_warnings': True,
            'extractaudio': False,
            'audioformat': 'mp3',
            'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], '%(title)s.%(ext)s'),
            'restrictfilenames': True,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
        }

    def get_video_info(self, url):
        """Extract comprehensive video information"""
        try:
            logger.info(f"Getting YouTube video info for: {url}")
            
            with yt_dlp.YoutubeDL(self.ydl_opts_base) as ydl:
                info = ydl.extract_info(url, download=False)

                formats = []
                seen_qualities = set()
                
                # Process video formats with real data
                for fmt in info.get('formats', []):
                    if fmt.get('vcodec') != 'none' and fmt.get('height'):
                        quality = f"{fmt['height']}p"
                        if quality not in seen_qualities:
                            formats.append({
                                'format_id': fmt['format_id'],
                                'quality': quality,
                                'filesize': fmt.get('filesize') or self._estimate_filesize(fmt),
                                'ext': fmt.get('ext', 'mp4'),
                                'type': 'video',
                                'fps': fmt.get('fps', 30),
                                'vcodec': fmt.get('vcodec', 'unknown'),
                                'acodec': fmt.get('acodec', 'unknown'),
                                'tbr': fmt.get('tbr', 0)
                            })
                            seen_qualities.add(quality)

                # Add audio formats
                for fmt in info.get('formats', []):
                    if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                        quality = f"{fmt.get('abr', 128)}kbps"
                        formats.append({
                            'format_id': fmt['format_id'],
                            'quality': quality,
                            'filesize': fmt.get('filesize') or self._estimate_audio_filesize(info.get('duration', 0)),
                            'ext': fmt.get('ext', 'mp4'),
                            'type': 'audio',
                            'abr': fmt.get('abr', 128),
                            'acodec': fmt.get('acodec', 'unknown')
                        })

                # Add MP3 option
                formats.append({
                    'format_id': 'bestaudio/best',
                    'quality': 'MP3',
                    'filesize': self._estimate_audio_filesize(info.get('duration', 0)),
                    'ext': 'mp3',
                    'type': 'audio',
                    'abr': 192
                })

                # Clean and format description
                description = info.get('description', '')
                if description and len(description) > 300:
                    description = description[:300] + '...'

                # Format upload date
                upload_date = info.get('upload_date', '')
                if upload_date:
                    try:
                        upload_date = datetime.strptime(upload_date, '%Y%m%d').strftime('%Y-%m-%d')
                    except:
                        pass

                result = {
                    'success': True,
                    'title': info.get('title', 'Unknown Video'),
                    'description': description,
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'uploader_id': info.get('uploader_id', ''),
                    'upload_date': upload_date,
                    'webpage_url': info.get('webpage_url', url),
                    'formats': sorted(formats, key=lambda x: self._sort_formats(x), reverse=True),
                    'categories': info.get('categories', []),
                    'tags': info.get('tags', [])[:10],  # Limit tags
                }
                
                logger.info(f"Successfully extracted info for: {result['title']}")
                return result

        except yt_dlp.DownloadError as e:
            logger.error(f"yt-dlp error for {url}: {str(e)}")
            return {'success': False, 'error': f'Video not available or private: {str(e)}'}
        except Exception as e:
            logger.error(f"Error getting YouTube video info for {url}: {str(e)}")
            return {'success': False, 'error': f'Failed to get video information: {str(e)}'}

    def _estimate_filesize(self, fmt):
        """Estimate filesize based on quality and duration"""
        try:
            tbr = fmt.get('tbr', 0)
            duration = fmt.get('duration', 0)
            if tbr and duration:
                return int(tbr * duration * 125)  # tbr is in kbps, convert to bytes
            return 0
        except:
            return 0

    def _estimate_audio_filesize(self, duration):
        """Estimate audio filesize"""
        if not duration:
            return 0
        return int(duration * 192 * 125)  # 192 kbps to bytes

    def _sort_formats(self, fmt):
        """Sort formats by quality preference"""
        quality_order = {'2160p': 2160, '1440p': 1440, '1080p': 1080, '720p': 720, '480p': 480, '360p': 360, '240p': 240, '144p': 144}
        quality = fmt.get('quality', '0p')
        return quality_order.get(quality, 0)

    def download_video(self, url, format_id, quality):
        """Download video with specified format and enhanced error handling"""
        try:
            logger.info(f"Starting download: {url} with format {format_id}")
            
            download_id = str(uuid.uuid4())
            timestamp = int(time.time())
            safe_filename = SecurityValidator.sanitize_filename(f"video_{timestamp}_{download_id[:8]}")

            opts = self.ydl_opts_base.copy()
            
            if quality == 'MP3' or format_id == 'bestaudio/best':
                opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], f'{safe_filename}.%(ext)s'),
                })
                expected_ext = 'mp3'
            else:
                opts.update({
                    'format': format_id,
                    'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], f'{safe_filename}.%(ext)s'),
                })
                expected_ext = 'mp4'

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = SecurityValidator.sanitize_filename(info.get('title', 'video'))

                # Find the downloaded file
                possible_files = []
                for ext in [expected_ext, 'mp4', 'webm', 'mkv', 'mp3', 'm4a']:
                    filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], f"{safe_filename}.{ext}")
                    if os.path.exists(filepath):
                        possible_files.append((filepath, ext))

                if not possible_files:
                    # Try to find any file that matches the pattern
                    import glob
                    pattern = os.path.join(app.config['DOWNLOAD_FOLDER'], f"{safe_filename}.*")
                    matches = glob.glob(pattern)
                    if matches:
                        filepath = matches[0]
                        ext = os.path.splitext(filepath)[1][1:]
                        possible_files.append((filepath, ext))

                if possible_files:
                    filepath, ext = possible_files[0]
                    filename = f"{safe_filename}.{ext}"
                    
                    # Create public download URL
                    download_url = f"{request.scheme}://{request.host}/api/file/{filename}"
                    
                    # Get file size
                    file_size = os.path.getsize(filepath)
                    
                    result = {
                        'success': True,
                        'filename': filename,
                        'title': title,
                        'download_url': download_url,
                        'filepath': filepath,
                        'file_size': file_size,
                        'download_id': download_id,
                        'format': f"{quality} {ext.upper()}",
                        'timestamp': timestamp
                    }
                    
                    logger.info(f"Download completed: {filename} ({file_size} bytes)")
                    return result
                else:
                    logger.error(f"Downloaded file not found for: {safe_filename}")
                    return {'success': False, 'error': 'Downloaded file not found'}

        except yt_dlp.DownloadError as e:
            logger.error(f"yt-dlp download error for {url}: {str(e)}")
            return {'success': False, 'error': f'Download failed: {str(e)}'}
        except Exception as e:
            logger.error(f"Error downloading YouTube video {url}: {str(e)}")
            return {'success': False, 'error': f'Download error: {str(e)}'}

class InstagramDownloader:
    """Enhanced Instagram media downloader with comprehensive features"""
    
    def __init__(self):
        try:
            self.loader = instaloader.Instaloader(
                quiet=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                request_timeout=30,
                max_connection_attempts=5
            )
            logger.info("Instagram loader initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Instagram loader: {e}")
            self.loader = None

    def get_media_info(self, url):
        """Get comprehensive Instagram media information"""
        try:
            if not self.loader:
                return {'success': False, 'error': 'Instagram loader not available'}
            
            logger.info(f"Getting Instagram media info for: {url}")
            
            shortcode = self.extract_shortcode(url)
            if not shortcode:
                return {'success': False, 'error': 'Invalid Instagram URL - could not extract shortcode'}

            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

            # Determine media type and URL
            if post.is_video:
                media_url = post.video_url
                media_type = 'video'
                ext = 'mp4'
                duration = post.video_duration if hasattr(post, 'video_duration') else 0
            else:
                media_url = post.url
                media_type = 'image'
                ext = 'jpg'
                duration = 0

            formats = [{
                'format_id': 'default',
                'quality': 'HD',
                'filesize': 0,  # Instagram doesn't provide file sizes
                'ext': ext,
                'type': media_type,
                'media_url': media_url
            }]

            # Get real caption and truncate if needed
            caption = post.caption or 'Instagram content'
            if len(caption) > 200:
                caption = caption[:200] + '...'

            # Format date
            post_date = ''
            if hasattr(post, 'date_utc') and post.date_utc:
                post_date = post.date_utc.strftime('%Y-%m-%d')

            result = {
                'success': True,
                'title': f"Instagram {media_type.title()} by @{post.owner_username}",
                'description': caption,
                'thumbnail': post.url,  # Use image URL as thumbnail
                'duration': duration,
                'view_count': 0,  # Instagram API doesn't provide view count
                'like_count': post.likes,
                'comment_count': post.comments,
                'uploader': post.owner_username,
                'uploader_id': post.owner_username,
                'upload_date': post_date,
                'webpage_url': f"https://www.instagram.com/p/{shortcode}/",
                'formats': formats,
                'is_video': post.is_video,
                'media_url': media_url,
                'shortcode': shortcode
            }
            
            logger.info(f"Successfully extracted Instagram info for: {shortcode}")
            return result

        except instaloader.exceptions.PostUnavailableException:
            logger.error(f"Instagram post not available: {shortcode}")
            return {'success': False, 'error': 'Post is private, deleted, or doesn\'t exist'}
        except instaloader.exceptions.ConnectionException as e:
            logger.error(f"Instagram connection error: {e}")
            return {'success': False, 'error': 'Connection to Instagram failed'}
        except Exception as e:
            logger.error(f"Error getting Instagram media info: {str(e)}")
            return {'success': False, 'error': f'Failed to get Instagram media info: {str(e)}'}

    def extract_shortcode(self, url):
        """Extract shortcode from Instagram URL with multiple patterns"""
        patterns = [
            r'instagram\.com/p/([A-Za-z0-9_-]+)',
            r'instagram\.com/reel/([A-Za-z0-9_-]+)',
            r'instagram\.com/tv/([A-Za-z0-9_-]+)',
            r'instagram\.com/stories/[^/]+/([A-Za-z0-9_-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        logger.warning(f"Could not extract shortcode from URL: {url}")
        return None

    def download_media(self, url):
        """Download Instagram media with enhanced error handling"""
        try:
            if not self.loader:
                return {'success': False, 'error': 'Instagram loader not available'}
            
            logger.info(f"Starting Instagram download: {url}")
            
            media_info = self.get_media_info(url)
            if not media_info['success']:
                return media_info

            download_id = str(uuid.uuid4())
            timestamp = int(time.time())
            safe_filename = SecurityValidator.sanitize_filename(f"instagram_{timestamp}_{download_id[:8]}")

            # Download the media with proper headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }

            response = requests.get(media_info['media_url'], 
                                  headers=headers, 
                                  stream=True, 
                                  timeout=30)
            response.raise_for_status()

            ext = 'mp4' if media_info['is_video'] else 'jpg'
            filename = f"{safe_filename}.{ext}"
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # Verify file was created and has content
            if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                return {'success': False, 'error': 'Failed to download media or file is empty'}

            # Create public download URL
            download_url = f"{request.scheme}://{request.host}/api/file/{filename}"
            file_size = os.path.getsize(filepath)

            result = {
                'success': True,
                'filename': filename,
                'title': media_info['title'],
                'download_url': download_url,
                'filepath': filepath,
                'file_size': file_size,
                'download_id': download_id,
                'format': f"HD {ext.upper()}",
                'timestamp': timestamp
            }
            
            logger.info(f"Instagram download completed: {filename} ({file_size} bytes)")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error downloading Instagram media: {e}")
            return {'success': False, 'error': f'Network error: {str(e)}'}
        except Exception as e:
            logger.error(f"Error downloading Instagram media: {str(e)}")
            return {'success': False, 'error': f'Download failed: {str(e)}'}

class FacebookDownloader:
    """Enhanced Facebook media downloader"""
    
    def get_media_info(self, url):
        """Get Facebook media info with enhanced extraction"""
        try:
            logger.info(f"Getting Facebook media info for: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Enhanced metadata extraction
            title = 'Facebook Video'
            description = 'Facebook video content'
            thumbnail = ''

            # Try multiple methods to extract title
            title_selectors = [
                'meta[property="og:title"]',
                'meta[name="twitter:title"]', 
                'title',
                'h1'
            ]
            
            for selector in title_selectors:
                element = soup.select_one(selector)
                if element:
                    title = element.get('content') or element.get_text()
                    if title:
                        title = title.strip()[:100]
                        break

            # Try to extract description
            desc_selectors = [
                'meta[property="og:description"]',
                'meta[name="description"]',
                'meta[name="twitter:description"]'
            ]
            
            for selector in desc_selectors:
                element = soup.select_one(selector)
                if element:
                    description = element.get('content', '')
                    if description:
                        description = description.strip()[:200]
                        break

            # Try to extract thumbnail
            thumbnail_selectors = [
                'meta[property="og:image"]',
                'meta[name="twitter:image"]'
            ]
            
            for selector in thumbnail_selectors:
                element = soup.select_one(selector)
                if element:
                    thumbnail = element.get('content', '')
                    break

            formats = [{
                'format_id': 'default',
                'quality': 'HD',
                'filesize': 0,
                'ext': 'mp4',
                'type': 'video'
            }]

            result = {
                'success': True,
                'title': title,
                'description': description,
                'thumbnail': thumbnail,
                'duration': 0,
                'view_count': 0,
                'uploader': 'Facebook User',
                'uploader_id': '',
                'upload_date': '',
                'webpage_url': url,
                'formats': formats,
                'is_video': True
            }
            
            logger.info(f"Successfully extracted Facebook info: {title}")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error getting Facebook info: {e}")
            return {'success': False, 'error': f'Network error: {str(e)}'}
        except Exception as e:
            logger.error(f"Error getting Facebook media info: {str(e)}")
            return {'success': False, 'error': f'Failed to get Facebook media info: {str(e)}'}

    def download_media(self, url):
        """Download Facebook media (Enhanced but simplified due to API restrictions)"""
        try:
            logger.info(f"Starting Facebook download: {url}")
            
            media_info = self.get_media_info(url)
            if not media_info['success']:
                return media_info

            download_id = str(uuid.uuid4())
            timestamp = int(time.time())
            safe_filename = SecurityValidator.sanitize_filename(f"facebook_{timestamp}_{download_id[:8]}")

            # For demonstration purposes - real Facebook video extraction 
            # would require more sophisticated methods due to their anti-bot measures
            
            # Create a placeholder info file instead of video
            filename = f"{safe_filename}.json"
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
            
            info_data = {
                'title': media_info['title'],
                'description': media_info['description'],
                'url': url,
                'extracted_at': datetime.now().isoformat(),
                'note': 'Facebook video extraction requires specialized tools due to platform restrictions'
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(info_data, f, indent=2)

            download_url = f"{request.scheme}://{request.host}/api/file/{filename}"
            file_size = os.path.getsize(filepath)

            result = {
                'success': True,
                'filename': filename,
                'title': media_info['title'],
                'download_url': download_url,
                'filepath': filepath,
                'file_size': file_size,
                'download_id': download_id,
                'format': 'JSON Info',
                'timestamp': timestamp,
                'note': 'Facebook video info extracted. Direct video download requires additional authentication.'
            }
            
            logger.info(f"Facebook info extraction completed: {filename}")
            return result

        except Exception as e:
            logger.error(f"Error downloading Facebook media: {str(e)}")
            return {'success': False, 'error': f'Download failed: {str(e)}'}

# Initialize downloaders with error handling
try:
    youtube_downloader = YouTubeDownloader()
    logger.info("YouTube downloader initialized")
except Exception as e:
    logger.error(f"Failed to initialize YouTube downloader: {e}")
    youtube_downloader = None

try:
    instagram_downloader = InstagramDownloader()
    logger.info("Instagram downloader initialized")
except Exception as e:
    logger.error(f"Failed to initialize Instagram downloader: {e}")
    instagram_downloader = None

try:
    facebook_downloader = FacebookDownloader()
    logger.info("Facebook downloader initialized")
except Exception as e:
    logger.error(f"Failed to initialize Facebook downloader: {e}")
    facebook_downloader = None

class ContactHandler:
    """Enhanced contact form and feedback handling"""
    
    @staticmethod
    def send_email(subject, body, to_email=None):
        """Send email notification with better error handling"""
        try:
            if not app.config.get('EMAIL_PASS'):
                logger.warning("Email password not configured")
                return False

            msg = MIMEMultipart()
            msg['From'] = app.config['EMAIL_USER']
            msg['To'] = to_email or app.config['EMAIL_USER']
            msg['Subject'] = subject

            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            with smtplib.SMTP(app.config['SMTP_SERVER'], app.config['SMTP_PORT']) as server:
                server.starttls()
                server.login(app.config['EMAIL_USER'], app.config['EMAIL_PASS'])
                server.send_message(msg)

            logger.info(f"Email sent successfully: {subject}")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error("Email authentication failed")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return False

    @staticmethod
    def save_to_file(data_type, data):
        """Save contact/feedback data with enhanced structure"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{data_type}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
            filepath = os.path.join(app.config['TEMP_FOLDER'], filename)

            # Add metadata
            enhanced_data = {
                'type': data_type,
                'timestamp': datetime.now().isoformat(),
                'user_agent': request.headers.get('User-Agent', ''),
                'ip_address': request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR')),
                'data': data
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(enhanced_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Data saved: {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving data: {str(e)}")
            return False

# Enhanced security headers
@app.after_request
def enhance_security_headers(response):
    """Add comprehensive security headers"""
    response.headers.update({
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self' https:",
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
        'Access-Control-Max-Age': '3600'
    })
    return response

# Static file serving
@app.route('/')
def serve_index():
    """Serve the main HTML file"""
    try:
        return send_from_directory('.', 'index.html')
    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Frontend files not found',
            'api_status': 'online'
        }), 404

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    try:
        return send_from_directory('.', filename)
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'File not found'}), 404

# Health check and status endpoints
@app.route('/health')
def health_check():
    """Comprehensive health check"""
    try:
        # Check downloaders
        downloaders_status = {
            'youtube': youtube_downloader is not None,
            'instagram': instagram_downloader is not None,
            'facebook': facebook_downloader is not None
        }
        
        # Check directories
        directories_status = {
            'download_folder': os.path.exists(app.config['DOWNLOAD_FOLDER']),
            'temp_folder': os.path.exists(app.config['TEMP_FOLDER']),
        }
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'version': '2.0.0',
            'environment': os.environ.get('FLASK_ENV', 'production'),
            'downloaders': downloaders_status,
            'directories': directories_status,
            'uptime': int(time.time()),
            'python_version': f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}"
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@app.route('/api/status')
def api_status():
    """Detailed API status"""
    return jsonify({
        'service': 'Downloader NinjaX API',
        'version': '2.0.0',
        'status': 'online',
        'timestamp': datetime.utcnow().isoformat(),
        'endpoints': {
            'analyze': '/api/analyze',
            'download': '/api/download',
            'contact': '/api/submit/contact',
            'feedback': '/api/submit/feedback',
            'file_download': '/api/file/<filename>',
            'health': '/health'
        },
        'supported_platforms': ['youtube', 'instagram', 'facebook'],
        'rate_limits': {
            'analyze': '20 per minute',
            'download': '10 per minute',
            'contact': '5 per minute'
        }
    })

# Main API endpoints
@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze_generic():
    """Generic analyze endpoint with comprehensive platform support"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Rate limiting
    if limiter:
        try:
            limiter.limit("20 per minute")(lambda: None)()
        except Exception:
            return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429
    
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ['url', 'platform']):
            return jsonify({
                'success': False, 
                'error': 'Missing required fields: url and platform'
            }), 400

        url = data['url'].strip()
        platform = data['platform'].lower()
        
        # Validate URL
        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        # Route to appropriate downloader
        result = None
        
        if platform == 'youtube':
            if not youtube_downloader:
                return jsonify({'success': False, 'error': 'YouTube downloader not available'}), 503
            if not re.search(r'(youtube\.com|youtu\.be)', url):
                return jsonify({'success': False, 'error': 'Invalid YouTube URL'}), 400
            result = youtube_downloader.get_video_info(url)
            
        elif platform == 'instagram':
            if not instagram_downloader:
                return jsonify({'success': False, 'error': 'Instagram downloader not available'}), 503
            if not re.search(r'instagram\.com', url):
                return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400
            result = instagram_downloader.get_media_info(url)
            
        elif platform == 'facebook':
            if not facebook_downloader:
                return jsonify({'success': False, 'error': 'Facebook downloader not available'}), 503
            if not re.search(r'facebook\.com', url):
                return jsonify({'success': False, 'error': 'Invalid Facebook URL'}), 400
            result = facebook_downloader.get_media_info(url)
            
        else:
            return jsonify({
                'success': False, 
                'error': f'Unsupported platform: {platform}. Supported: youtube, instagram, facebook'
            }), 400

        if result:
            logger.info(f"Successfully analyzed {platform} URL")
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': 'Analysis failed'}), 500

    except Exception as e:
        logger.error(f"Error in analyze_generic: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/download', methods=['POST', 'OPTIONS'])
def download_generic():
    """Generic download endpoint with comprehensive error handling"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Rate limiting
    if limiter:
        try:
            limiter.limit("10 per minute")(lambda: None)()
        except Exception:
            return jsonify({'success': False, 'error': 'Download rate limit exceeded'}), 429
    
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ['url', 'platform']):
            return jsonify({
                'success': False, 
                'error': 'Missing required fields: url and platform'
            }), 400

        url = data['url'].strip()
        platform = data['platform'].lower()
        quality = data.get('quality', 'best')
        format_id = data.get('format_id', quality)
        
        # Validate URL
        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        # Route to appropriate downloader
        result = None
        
        if platform == 'youtube':
            if not youtube_downloader:
                return jsonify({'success': False, 'error': 'YouTube downloader not available'}), 503
            result = youtube_downloader.download_video(url, format_id, quality)
            
        elif platform == 'instagram':
            if not instagram_downloader:
                return jsonify({'success': False, 'error': 'Instagram downloader not available'}), 503
            result = instagram_downloader.download_media(url)
            
        elif platform == 'facebook':
            if not facebook_downloader:
                return jsonify({'success': False, 'error': 'Facebook downloader not available'}), 503
            result = facebook_downloader.download_media(url)
            
        else:
            return jsonify({
                'success': False, 
                'error': f'Unsupported platform: {platform}'
            }), 400

        if result:
            logger.info(f"Successfully processed download for {platform}")
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': 'Download failed'}), 500

    except Exception as e:
        logger.error(f"Error in download_generic: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/submit/contact', methods=['POST', 'OPTIONS'])
def submit_contact():
    """Enhanced contact form submission"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Rate limiting
    if limiter:
        try:
            limiter.limit("5 per minute")(lambda: None)()
        except Exception:
            return jsonify({'success': False, 'error': 'Contact rate limit exceeded'}), 429
    
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ['email', 'subject', 'message']):
            return jsonify({
                'success': False, 
                'error': 'Missing required fields: email, subject, message'
            }), 400

        # Validate email format
        email = data['email'].strip()
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({'success': False, 'error': 'Invalid email format'}), 400

        # Save to file
        ContactHandler.save_to_file('contact', data)

        # Prepare and send email
        subject = f"Downloader NinjaX Contact: {data['subject']}"
        body = f"""
New Contact Form Submission

From: {email}
Subject: {data['subject']}
Timestamp: {data.get('timestamp', datetime.now().isoformat())}
User Agent: {request.headers.get('User-Agent', 'Unknown')}

Message:
{data['message']}

---
Downloader NinjaX Contact System
        """

        # Try to send email (optional)
        email_sent = ContactHandler.send_email(subject, body)

        response_data = {
            'success': True, 
            'message': 'Contact form submitted successfully',
            'email_sent': email_sent
        }
        
        if not email_sent:
            response_data['note'] = 'Form saved but email notification failed'

        logger.info(f"Contact form submitted by {email}")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error in submit_contact: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/submit/feedback', methods=['POST', 'OPTIONS'])
def submit_feedback():
    """Enhanced feedback form submission"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Rate limiting
    if limiter:
        try:
            limiter.limit("5 per minute")(lambda: None)()
        except Exception:
            return jsonify({'success': False, 'error': 'Feedback rate limit exceeded'}), 429
    
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ['type', 'message']):
            return jsonify({
                'success': False, 
                'error': 'Missing required fields: type, message'
            }), 400

        # Validate feedback type
        valid_types = ['suggestion', 'bug', 'compliment', 'complaint', 'feature']
        if data['type'] not in valid_types:
            return jsonify({'success': False, 'error': f'Invalid feedback type. Valid types: {valid_types}'}), 400

        # Save to file
        ContactHandler.save_to_file('feedback', data)

        # Prepare email
        feedback_type = data['type'].replace('_', ' ').title()
        subject = f"Downloader NinjaX Feedback: {feedback_type}"
        
        body = f"""
New Feedback Submission

Type: {feedback_type}
Rating: {data.get('rating', 'Not provided')}/5 stars
Email: {data.get('email', 'Not provided')}
Timestamp: {data.get('timestamp', datetime.now().isoformat())}
User Agent: {request.headers.get('User-Agent', 'Unknown')}

Message:
{data['message']}

---
Downloader NinjaX Feedback System
        """

        # Try to send email (optional)
        email_sent = ContactHandler.send_email(subject, body)

        response_data = {
            'success': True, 
            'message': 'Feedback submitted successfully',
            'email_sent': email_sent
        }
        
        if not email_sent:
            response_data['note'] = 'Feedback saved but email notification failed'

        logger.info(f"Feedback submitted: {data['type']}")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error in submit_feedback: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/file/<path:filename>')
def download_file(filename):
    """Enhanced secure file download endpoint"""
    try:
        # Sanitize filename
        safe_filename = SecurityValidator.sanitize_filename(filename)
        
        # Validate file extension
        if not SecurityValidator.validate_file_extension(safe_filename):
            logger.warning(f"Blocked file download attempt: {filename}")
            abort(403)
        
        filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], safe_filename)

        # Security check - ensure file is in download directory
        if not os.path.abspath(filepath).startswith(os.path.abspath(app.config['DOWNLOAD_FOLDER'])):
            logger.warning(f"Path traversal attempt detected: {filename}")
            abort(403)

        if not os.path.exists(filepath):
            logger.info(f"File not found: {safe_filename}")
            abort(404)

        # Get file info
        file_size = os.path.getsize(filepath)
        logger.info(f"Serving file: {safe_filename} ({file_size} bytes)")

        return send_file(
            filepath, 
            as_attachment=True, 
            download_name=safe_filename,
            mimetype='application/octet-stream'
        )

    except Exception as e:
        logger.error(f"Error in download_file: {str(e)}")
        abort(500)

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False, 
        'error': 'Endpoint not found',
        'available_endpoints': ['/api/analyze', '/api/download', '/api/submit/contact', '/api/submit/feedback', '/health']
    }), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        'success': False, 
        'error': 'Rate limit exceeded. Please wait before trying again.',
        'retry_after': '60 seconds'
    }), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({
        'success': False, 
        'error': 'Internal server error'
    }), 500

@app.errorhandler(413)
def too_large(error):
    return jsonify({
        'success': False, 
        'error': 'File too large. Maximum size allowed: 500MB'
    }), 413

# Background cleanup and maintenance
def cleanup_old_files():
    """Enhanced cleanup function with better logging"""
    try:
        current_time = time.time()
        cleaned_files = 0
        
        # Clean download files (older than 2 hours)
        download_folder = app.config['DOWNLOAD_FOLDER']
        if os.path.exists(download_folder):
            for filename in os.listdir(download_folder):
                filepath = os.path.join(download_folder, filename)
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getctime(filepath)
                    if file_age > 7200:  # 2 hours
                        try:
                            os.remove(filepath)
                            cleaned_files += 1
                            logger.info(f"Deleted old download file: {filename}")
                        except OSError as e:
                            logger.error(f"Failed to delete {filename}: {e}")

        # Clean temp files (older than 24 hours)
        temp_folder = app.config['TEMP_FOLDER']
        if os.path.exists(temp_folder):
            for filename in os.listdir(temp_folder):
                filepath = os.path.join(temp_folder, filename)
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getctime(filepath)
                    if file_age > 86400:  # 24 hours
                        try:
                            os.remove(filepath)
                            cleaned_files += 1
                            logger.info(f"Deleted old temp file: {filename}")
                        except OSError as e:
                            logger.error(f"Failed to delete {filename}: {e}")
        
        if cleaned_files > 0:
            logger.info(f"Cleanup completed: {cleaned_files} files deleted")
                    
    except Exception as e:
        logger.error(f"Error in cleanup: {str(e)}")

def periodic_cleanup():
    """Periodic cleanup in background thread"""
    while True:
        try:
            cleanup_old_files()
            time.sleep(3600)  # Run every hour
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")
            time.sleep(3600)

def periodic_health_check():
    """Periodic health check"""
    while True:
        try:
            # Log system status
            logger.info("Periodic health check - System running normally")
            time.sleep(300)  # Run every 5 minutes
        except Exception as e:
            logger.error(f"Health check error: {e}")
            time.sleep(300)

# Start background threads
cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
cleanup_thread.start()
logger.info("Background cleanup thread started")

health_thread = threading.Thread(target=periodic_health_check, daemon=True)
health_thread.start()
logger.info("Background health check thread started")

# Run initial cleanup
cleanup_old_files()

# Application startup
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info("="*50)
    logger.info("DOWNLOADER NINJAX API STARTING")
    logger.info("="*50)
    logger.info(f"Version: 2.0.0")
    logger.info(f"Host: {host}")
    logger.info(f"Port: {port}")
    logger.info(f"Debug: {debug}")
    logger.info(f"Download folder: {app.config['DOWNLOAD_FOLDER']}")
    logger.info(f"Temp folder: {app.config['TEMP_FOLDER']}")
    logger.info(f"Downloaders available:")
    logger.info(f"  - YouTube: {'✓' if youtube_downloader else '✗'}")
    logger.info(f"  - Instagram: {'✓' if instagram_downloader else '✗'}")
    logger.info(f"  - Facebook: {'✓' if facebook_downloader else '✗'}")
    logger.info("="*50)
    
    app.run(host=host, port=port, debug=debug, threaded=True)
