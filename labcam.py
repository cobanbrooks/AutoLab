from flask import Flask, Response, render_template, request, redirect, url_for
from functools import wraps
import cv2
import threading
import datetime
import sys
import platform
import argparse
import hashlib
import getpass
import logging
import numpy as np

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('labcam')

def check_password(password):
    """Check if password matches the stored hash"""
    return hashlib.sha256(password.encode()).hexdigest() == PASSWORD_HASH

def requires_auth(f):
    """Decorator to require password authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        password = request.args.get('password')
        if not password or not check_password(password):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

class Camera:
    def __init__(self, camera_id, name):
        self.name = name
        self.camera_id = camera_id
        self.camera = None
        self.frame = None
        self.running = False
        self._lock = threading.Lock()
        self.error = None
        
    def start(self):
        """Start the camera capture thread"""
        try:
            logger.info(f"Initializing camera {self.name} (ID: {self.camera_id})")
            self.camera = cv2.VideoCapture(self.camera_id)
            
            # Check if camera opened successfully
            if not self.camera.isOpened():
                self.error = f"Could not open camera {self.name} (ID: {self.camera_id})"
                logger.error(self.error)
                return False
            
            # Try to read a test frame
            ret, frame = self.camera.read()
            if not ret or frame is None:
                self.error = f"Could not read initial frame from camera {self.name}"
                logger.error(self.error)
                return False
                
            logger.info(f"Successfully read initial frame from camera {self.name}")
            logger.info(f"Frame shape: {frame.shape}")
                
            # Set lower resolution to help with performance
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            self.running = True
            threading.Thread(target=self._capture_loop, daemon=True).start()
            logger.info(f"Successfully started camera: {self.name}")
            return True
            
        except Exception as e:
            self.error = f"Error initializing camera {self.name}: {str(e)}"
            logger.error(self.error, exc_info=True)
            return False
        
    def stop(self):
        """Stop the camera"""
        self.running = False
        if self.camera is not None:
            self.camera.release()
        
    def _capture_loop(self):
        """Continuously capture frames from the camera"""
        frame_count = 0
        last_log = datetime.datetime.now()
        
        while self.running:
            try:
                if self.camera is None or not self.camera.isOpened():
                    self.error = f"Error: Camera {self.name} is not open"
                    logger.error(self.error)
                    break
                    
                success, frame = self.camera.read()
                if success:
                    with self._lock:
                        self.frame = frame
                        frame_count += 1
                        
                        # Log frame rate every 5 seconds
                        now = datetime.datetime.now()
                        if (now - last_log).seconds >= 5:
                            fps = frame_count / 5
                            logger.debug(f"Camera {self.name} capturing at {fps:.1f} FPS")
                            frame_count = 0
                            last_log = now
                else:
                    self.error = f"Failed to read frame from camera {self.name}"
                    logger.warning(self.error)
                    
            except Exception as e:
                self.error = f"Error capturing frame from {self.name}: {str(e)}"
                logger.error(self.error, exc_info=True)
                break
                
        self.running = False
    
    def get_frame(self):
        """Get the current frame with timestamp and error message if applicable"""
        with self._lock:
            if self.frame is None:
                # Create an error frame
                frame = np.zeros((480, 640, 3), np.uint8)
                cv2.putText(frame, "No video signal", (50, 240), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                if self.error:
                    cv2.putText(frame, self.error, (50, 270), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            else:
                frame = self.frame.copy()
            
            try:
                # Add timestamp
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(frame, timestamp, (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                # Add error message if exists
                if self.error:
                    cv2.putText(frame, self.error, (10, 60), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                
                # Encode frame to JPEG
                ret, buffer = cv2.imencode('.jpg', frame)
                if not ret:
                    raise Exception("Failed to encode frame")
                    
                return buffer.tobytes()
                
            except Exception as e:
                logger.error(f"Error processing frame from {self.name}: {str(e)}", exc_info=True)
                return None

# Initialize Flask app
app = Flask(__name__)

# Will be initialized after camera selection
cameras = {}

def generate_frames(camera_name):
    """Generate frames for video streaming"""
    camera = cameras.get(camera_name)
    if not camera:
        return
        
    while True:
        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/login')
def login():
    """Show login page"""
    return '''
    <html>
    <head>
        <title>Lab Monitor - Login</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .login { max-width: 400px; margin: 0 auto; }
        </style>
    </head>
    <body>
        <div class="login">
            <h2>Lab Monitor Login</h2>
            <p>Enter the password to view the streams:</p>
            <form action="/auth" method="get">
                <input type="password" name="password" style="width: 100%; padding: 8px;">
                <input type="submit" value="Access Streams" style="margin-top: 10px; padding: 8px;">
            </form>
        </div>
    </body>
    </html>
    '''

@app.route('/auth')
def auth():
    """Handle authentication"""
    password = request.args.get('password')
    if check_password(password):
        return redirect(url_for('index', password=password))
    return redirect(url_for('login'))

@app.route('/')
@requires_auth
def index():
    """Render main page with all camera streams"""
    password = request.args.get('password')
    streams_html = ""
    for cam_name in cameras:
        streams_html += f'''
        <div class="camera-container">
            <h2>{cam_name}</h2>
            <img class="stream" src="/video_feed/{cam_name}?password={password}" />
        </div>
        '''
    
    return f'''
    <html>
    <head>
        <title>Lab Monitor</title>
        <style>
            .camera-container {{ margin: 20px; }}
            .stream {{ max-width: 800px; }}
        </style>
    </head>
    <body>
        {streams_html}
    </body>
    </html>
    '''

@app.route('/video_feed/<camera_name>')
@requires_auth
def video_feed(camera_name):
    """Video streaming route"""
    return Response(
        generate_frames(camera_name),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Lab Camera Stream')
    parser.add_argument('--host', default='0.0.0.0', help='Host IP address')
    parser.add_argument('--port', type=int, default=8000, help='Port number')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Get password from user
    password = getpass.getpass("Enter password for stream access: ")
    if not password:
        print("Error: Password cannot be empty")
        sys.exit(1)
    
    # Store password hash globally
    global PASSWORD_HASH
    PASSWORD_HASH = hashlib.sha256(password.encode()).hexdigest()
    
    # Print system info
    logger.info(f"Operating System: {platform.system()} {platform.release()}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"OpenCV version: {cv2.__version__}")
    
    # Get list of video devices on Linux
    if platform.system() == 'Linux':
        from pathlib import Path
        video_devices = list(Path('/dev').glob('video*'))
        logger.info(f"Available video devices: {video_devices}")
    
    # List available cameras
    print("\nScanning for available cameras...")
    available_cameras = []
    for i in range(10):  # Check first 10 indices
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                name = f"Camera {i}"
                available_cameras.append((i, name))
            cap.release()
    
    if not available_cameras:
        print("No cameras found!")
        sys.exit(1)
    
    print("\nAvailable cameras:")
    for i, (camera_id, name) in enumerate(available_cameras):
        print(f"{i+1}. {name} (ID: {camera_id})")
    
    # Let user select cameras
    try:
        print("\nEnter the numbers of the cameras you want to use (comma-separated):")
        selections = input("> ").strip().split(',')
        selected_indices = [int(s.strip())-1 for s in selections if s.strip()]
        
        for idx in selected_indices:
            if 0 <= idx < len(available_cameras):
                camera_id, name = available_cameras[idx]
                cameras[f"Camera_{camera_id}"] = Camera(camera_id, name)
    
    except (ValueError, IndexError) as e:
        print(f"Error selecting cameras: {str(e)}")
        sys.exit(1)
    
    if not cameras:
        print("No cameras selected!")
        sys.exit(1)
    
    # Start selected cameras
    started_cameras = []
    for name, camera in cameras.items():
        if camera.start():
            started_cameras.append(name)
    
    if not started_cameras:
        print("Error: No cameras could be started")
        sys.exit(1)
    
    print(f"\nStarted {len(started_cameras)} cameras: {', '.join(started_cameras)}")
    
    # Print access information
    print(f"\nAccess URLs:")
    print(f"Local: http://localhost:{args.port}/")
    if args.host == '0.0.0.0':
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        print(f"Network: http://{local_ip}:{args.port}/")
    
    try:
        print(f"\nStarting web server on {args.host}:{args.port}...")
        app.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"\nError starting server: {str(e)}")
    finally:
        for camera in cameras.values():
            camera.stop()