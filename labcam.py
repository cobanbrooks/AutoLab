from flask import Flask, Response, render_template
import cv2
import threading
import datetime

class Camera:
    def __init__(self, camera_id, name):
        self.name = name
        self.camera = cv2.VideoCapture(camera_id)
        # Disable audio capture
        self.camera.set(cv2.CAP_PROP_AUDIO_ENABLED, 0)
        # Double check audio is disabled
        if self.camera.get(cv2.CAP_PROP_AUDIO_ENABLED) != 0:
            raise RuntimeError(f"Failed to disable audio for camera {name}")
        self.frame = None
        self.running = False
        self._lock = threading.Lock()
        
    def start(self):
        """Start the camera capture thread"""
        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        
    def stop(self):
        """Stop the camera"""
        self.running = False
        self.camera.release()
        
    def _capture_loop(self):
        """Continuously capture frames from the camera"""
        while self.running:
            success, frame = self.camera.read()
            if success:
                with self._lock:
                    self.frame = frame
    
    def get_frame(self):
        """Get the current frame with timestamp"""
        with self._lock:
            if self.frame is None:
                return None
            
            frame = self.frame.copy()
            # Add timestamp
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, timestamp, (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            # Encode frame to JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                return None
                
            return buffer.tobytes()

# Initialize Flask app
app = Flask(__name__)

# Create cameras dict
cameras = {
    'bench': Camera(0, 'Lab Bench'),
    'plate_reader': Camera(1, 'Plate Reader')
}

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

@app.route('/')
def index():
    """Render main page with all camera streams"""
    return '''
    <html>
    <head>
        <title>Lab Monitor</title>
        <style>
            .camera-container { margin: 20px; }
            .stream { max-width: 800px; }
        </style>
    </head>
    <body>
        <div class="camera-container">
            <h2>Lab Bench</h2>
            <img class="stream" src="/video_feed/bench" />
        </div>
        <div class="camera-container">
            <h2>Plate Reader</h2>
            <img class="stream" src="/video_feed/plate_reader" />
        </div>
    </body>
    </html>
    '''

@app.route('/video_feed/<camera_name>')
def video_feed(camera_name):
    """Video streaming route"""
    return Response(
        generate_frames(camera_name),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

if __name__ == '__main__':
    # Start all cameras
    for camera in cameras.values():
        camera.start()
    
    try:
        # Run the Flask app
        app.run(host='0.0.0.0', port=5000)
    finally:
        # Stop all cameras on exit
        for camera in cameras.values():
            camera.stop()