import os
import re
import json
import time
import uuid
import hashlib
import logging
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse, parse_qs
import asyncio
from concurrent.futures import ThreadPoolExecutor
import zipfile

from flask import Flask, request, jsonify, send_file, render_template_string, abort
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
import yt_dlp
import instaloader
import requests
from bs4 import BeautifulSoup
import validators


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', str(uuid.uuid4()))
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 100  # 100MB max
app.config['DOWNLOAD_FOLDER'] = 'downloads'
app.config['TEMP_FOLDER'] = 'temp'

# Security headers
@app.after_request
def after_request(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    return response

# CORS configuration
CORS(app, origins=['*'], methods=['GET', 'POST', 'OPTIONS'])

# Rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["1000 per hour", "50 per minute"]
)

# Create directories
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)

# Thread pool for async operations
executor = ThreadPoolExecutor(max_workers=10)



class SecurityValidator:
    """Security validation for URLs and inputs"""

    BLOCKED_DOMAINS = [
        'localhost', '127.0.0.1', '0.0.0.0', '::1',
        'internal', 'private', 'admin'
    ]

    @staticmethod
    def validate_url(url):
        """Validate URL for security"""
        if not validators.url(url):
            return False, "Invalid URL format"

        parsed = urlparse(url)

        # Check for blocked domains
        if any(blocked in parsed.netloc.lower() for blocked in SecurityValidator.BLOCKED_DOMAINS):
            return False, "Access to this domain is not allowed"

        # Check for suspicious patterns
        if re.search(r'[<>"\'\\]', url):
            return False, "URL contains invalid characters"

        return True, "Valid URL"

    @staticmethod
    def sanitize_filename(filename):
        """Sanitize filename to prevent path traversal"""
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip('. ')
        return filename[:200]  # Limit filename length


class YouTubeDownloader:
    """YouTube video downloader with security measures"""

    def __init__(self):
        self.ydl_opts_base = {
            'quiet': True,
            'no_warnings': True,
            'extractaudio': False,
            'audioformat': 'mp3',
            'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], '%(title)s.%(ext)s'),
            'restrictfilenames': True,
        }

    def get_video_info(self, url):
        """Extract video information"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts_base) as ydl:
                info = ydl.extract_info(url, download=False)

                formats = []
                seen_qualities = set()

                # Process video formats
                for fmt in info.get('formats', []):
                    if fmt.get('vcodec') != 'none' and fmt.get('height'):
                        quality = f"{fmt['height']}p"
                        if quality not in seen_qualities:
                            formats.append({
                                'format_id': fmt['format_id'],
                                'quality': quality,
                                'filesize': fmt.get('filesize', 0) or 0,
                                'ext': fmt.get('ext', 'mp4'),
                                'type': 'video'
                            })
                            seen_qualities.add(quality)

                # Add audio format
                formats.append({
                    'format_id': 'bestaudio/best',
                    'quality': 'MP3',
                    'filesize': info.get('filesize', 0) or 0,
                    'ext': 'mp3',
                    'type': 'audio'
                })

                return {
                    'title': info.get('title', 'Unknown'),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'formats': formats,
                    'success': True
                }

        except Exception as e:
            logger.error(f"Error getting YouTube video info: {str(e)}")
            return {'success': False, 'error': str(e)}

    def download_video(self, url, format_id, quality):
        """Download video with specified format"""
        try:
            download_id = str(uuid.uuid4())
            safe_filename = SecurityValidator.sanitize_filename(f"Downloader_NinjaX_{download_id}")

            opts = self.ydl_opts_base.copy()

            if quality == 'MP3':
                opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], f'{safe_filename}.%(ext)s'),
                })
            else:
                opts.update({
                    'format': format_id,
                    'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], f'{safe_filename}.%(ext)s'),
                })

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video')

                # Find the downloaded file
                ext = 'mp3' if quality == 'MP3' else 'mp4'
                filename = f"{safe_filename}.{ext}"
                filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)

                if os.path.exists(filepath):
                    return {
                        'success': True,
                        'filename': filename,
                        'title': title,
                        'filepath': filepath,
                        'download_id': download_id
                    }
                else:
                    return {'success': False, 'error': 'File not found after download'}

        except Exception as e:
            logger.error(f"Error downloading YouTube video: {str(e)}")
            return {'success': False, 'error': str(e)}



class InstagramDownloader:
    """Instagram media downloader"""

    def __init__(self):
        self.loader = instaloader.Instaloader(
            quiet=True,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            request_timeout=30
        )

    def get_media_info(self, url):
        """Get Instagram media information"""
        try:
            shortcode = self.extract_shortcode(url)
            if not shortcode:
                return {'success': False, 'error': 'Invalid Instagram URL'}

            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

            return {
                'success': True,
                'title': post.caption[:100] if post.caption else 'Instagram Media',
                'thumbnail': post.url,
                'is_video': post.is_video,
                'media_url': post.video_url if post.is_video else post.url,
                'shortcode': shortcode
            }

        except Exception as e:
            logger.error(f"Error getting Instagram media info: {str(e)}")
            return {'success': False, 'error': str(e)}

    def extract_shortcode(self, url):
        """Extract shortcode from Instagram URL"""
        patterns = [
            r'instagram\.com/p/([^/?]+)',
            r'instagram\.com/reel/([^/?]+)',
            r'instagram\.com/tv/([^/?]+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def download_media(self, url):
        """Download Instagram media"""
        try:
            media_info = self.get_media_info(url)
            if not media_info['success']:
                return media_info

            download_id = str(uuid.uuid4())
            safe_filename = SecurityValidator.sanitize_filename(f"Downloader_NinjaX_{download_id}")

            # Download the media
            response = requests.get(media_info['media_url'], stream=True, timeout=30)
            response.raise_for_status()

            ext = 'mp4' if media_info['is_video'] else 'jpg'
            filename = f"{safe_filename}.{ext}"
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return {
                'success': True,
                'filename': filename,
                'title': media_info['title'],
                'filepath': filepath,
                'download_id': download_id
            }

        except Exception as e:
            logger.error(f"Error downloading Instagram media: {str(e)}")
            return {'success': False, 'error': str(e)}


class FacebookDownloader:
    """Facebook media downloader"""

    def get_media_info(self, url):
        """Get Facebook media information"""
        try:
            # Simple implementation - in production, you'd want more robust parsing
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Try to find video URL (simplified)
            video_tags = soup.find_all(['video', 'source'])
            for tag in video_tags:
                src = tag.get('src')
                if src and 'video' in src:
                    return {
                        'success': True,
                        'title': 'Facebook Video',
                        'media_url': src,
                        'is_video': True
                    }

            return {'success': False, 'error': 'No video found'}

        except Exception as e:
            logger.error(f"Error getting Facebook media info: {str(e)}")
            return {'success': False, 'error': str(e)}

    def download_media(self, url):
        """Download Facebook media"""
        try:
            media_info = self.get_media_info(url)
            if not media_info['success']:
                return media_info

            download_id = str(uuid.uuid4())
            safe_filename = SecurityValidator.sanitize_filename(f"Downloader_NinjaX_{download_id}")

            # Download the media
            response = requests.get(media_info['media_url'], stream=True, timeout=30)
            response.raise_for_status()

            filename = f"{safe_filename}.mp4"
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return {
                'success': True,
                'filename': filename,
                'title': media_info['title'],
                'filepath': filepath,
                'download_id': download_id
            }

        except Exception as e:
            logger.error(f"Error downloading Facebook media: {str(e)}")
            return {'success': False, 'error': str(e)}

# Initialize downloaders
youtube_downloader = YouTubeDownloader()
instagram_downloader = InstagramDownloader()
facebook_downloader = FacebookDownloader()



# API Routes
@app.route('/')
def index():
    """Serve the main page"""
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Downloader NinjaX API</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }
            h1 { color: #333; text-align: center; }
            .endpoint { background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; }
            code { background: #e9ecef; padding: 2px 4px; border-radius: 3px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>ðŸ¥· Downloader NinjaX API</h1>
            <p>Fast, secure, and reliable video/audio downloader API</p>

            <h2>Available Endpoints:</h2>

            <div class="endpoint">
                <h3>YouTube</h3>
                <p><strong>Get Info:</strong> <code>POST /api/youtube/info</code></p>
                <p><strong>Download:</strong> <code>POST /api/youtube/download</code></p>
            </div>

            <div class="endpoint">
                <h3>Instagram</h3>
                <p><strong>Get Info:</strong> <code>POST /api/instagram/info</code></p>
                <p><strong>Download:</strong> <code>POST /api/instagram/download</code></p>
            </div>

            <div class="endpoint">
                <h3>Facebook</h3>
                <p><strong>Get Info:</strong> <code>POST /api/facebook/info</code></p>
                <p><strong>Download:</strong> <code>POST /api/facebook/download</code></p>
            </div>

            <h2>Usage:</h2>
            <p>Send POST requests with JSON body containing the URL:</p>
            <pre><code>{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}</code></pre>
        </div>
    </body>
    </html>
    """
    return html_template

@app.route('/api/youtube/info', methods=['POST'])
@limiter.limit("10 per minute")
def youtube_info():
    """Get YouTube video information"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        url = data['url'].strip()
        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        # Check if it's a YouTube URL
        if not re.search(r'(youtube\.com|youtu\.be)', url):
            return jsonify({'success': False, 'error': 'Invalid YouTube URL'}), 400

        result = youtube_downloader.get_video_info(url)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in youtube_info: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/youtube/download', methods=['POST'])
@limiter.limit("5 per minute")
def youtube_download():
    """Download YouTube video"""
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ['url', 'format_id', 'quality']):
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400

        url = data['url'].strip()
        format_id = data['format_id']
        quality = data['quality']

        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        result = youtube_downloader.download_video(url, format_id, quality)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in youtube_download: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/instagram/info', methods=['POST'])
@limiter.limit("10 per minute")
def instagram_info():
    """Get Instagram media information"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        url = data['url'].strip()
        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        if not re.search(r'instagram\.com', url):
            return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

        result = instagram_downloader.get_media_info(url)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in instagram_info: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500



@app.route('/api/instagram/download', methods=['POST'])
@limiter.limit("5 per minute")
def instagram_download():
    """Download Instagram media"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        url = data['url'].strip()
        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        result = instagram_downloader.download_media(url)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in instagram_download: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/facebook/info', methods=['POST'])
@limiter.limit("10 per minute")
def facebook_info():
    """Get Facebook media information"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        url = data['url'].strip()
        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        if not re.search(r'facebook\.com', url):
            return jsonify({'success': False, 'error': 'Invalid Facebook URL'}), 400

        result = facebook_downloader.get_media_info(url)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in facebook_info: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/facebook/download', methods=['POST'])
@limiter.limit("5 per minute")
def facebook_download():
    """Download Facebook media"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        url = data['url'].strip()
        is_valid, message = SecurityValidator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400

        result = facebook_downloader.download_media(url)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in facebook_download: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/download/<path:filename>')
def download_file(filename):
    """Secure file download endpoint"""
    try:
        # Sanitize filename
        safe_filename = SecurityValidator.sanitize_filename(filename)
        filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], safe_filename)

        # Security check - ensure file is in download directory
        if not os.path.abspath(filepath).startswith(os.path.abspath(app.config['DOWNLOAD_FOLDER'])):
            abort(403)

        if not os.path.exists(filepath):
            abort(404)

        return send_file(filepath, as_attachment=True, download_name=filename)

    except Exception as e:
        logger.error(f"Error in download_file: {str(e)}")
        abort(500)

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0'
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# Cleanup old files
def cleanup_old_files():
    """Clean up old download files"""
    try:
        current_time = time.time()
        for filename in os.listdir(app.config['DOWNLOAD_FOLDER']):
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
            if os.path.isfile(filepath):
                # Delete files older than 1 hour
                if current_time - os.path.getctime(filepath) > 3600:
                    os.remove(filepath)
                    logger.info(f"Deleted old file: {filename}")
    except Exception as e:
        logger.error(f"Error cleaning up files: {str(e)}")

# Run cleanup on startup
cleanup_old_files()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
