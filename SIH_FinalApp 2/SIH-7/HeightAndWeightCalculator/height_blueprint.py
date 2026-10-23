from flask import Blueprint, render_template, Response, jsonify, request, session, current_app
from error_logger import log_error, log_warning, log_info
from session_manager import login_required, get_current_user
from db_config import get_db
import cv2
import numpy as np
import threading
import time
import json
import os
from datetime import datetime
from pathlib import Path
from bson import ObjectId
# integrated_system pulls in PyTorch; it is imported lazily in get_system()
from identity_guard import LiveIdentityMonitor, exercise_gate
from perf import open_camera, release_camera, FrameThrottle, encode_jpeg, mjpeg_chunk, limit_threads

# Create blueprint
height_bp = Blueprint('height', __name__,
                    template_folder='templates',
                    static_folder='static',
                    url_prefix='/height')

# Global variables for video processing
camera = None
is_recording = False
session_active = False
system = None
identity_error = False
# Re-checks the athlete's face every 2 s in a background thread during the measurement
identity_monitor = LiveIdentityMonitor(interval=2.0, max_strikes=3)

def get_system():
    global system
    if system is None:
        from integrated_system import IntegratedHeightWeightSystem
        system = IntegratedHeightWeightSystem(use_gpu=True)
        limit_threads()   # PyTorch is loaded now - cap its CPU threads too
    return system

def generate_frames():
    """Stream frames with height/weight overlay; identity is re-checked in the background."""
    global camera, is_recording, system, identity_error
    
    sys = get_system()
    measurements_history = []
    throttle = FrameThrottle(12)
    try:
        while is_recording and camera is not None:
            success, frame = camera.read()
            if not success:
                time.sleep(0.05)
                continue
            
            identity_monitor.submit(frame)          # non-blocking background face check
            if identity_monitor.terminated:
                log_error("Height: session stopped - a different person was detected")
                identity_error = True
                is_recording = False
                break
            
            try:
                result = sys.process_frame_integrated(frame)
                measurements_history.append(result)
                if len(measurements_history) > 10:
                    measurements_history.pop(0)
                
                sys.fps_counter += 1
                if sys.fps_counter % 30 == 0:
                    fps_end_time = time.time()
                    sys.current_fps = 30 / (fps_end_time - sys.fps_start_time)
                    sys.fps_start_time = fps_end_time
                
                sys._draw_integrated_ui(frame, result, measurements_history)
            except Exception as e:
                log_error(f"Processing error in height video feed: {e}")
                cv2.putText(frame, "Processing Error", (50, 50),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            identity_monitor.draw(frame)
            yield mjpeg_chunk(encode_jpeg(frame))
            throttle.wait()
    finally:
        # The stream ended (session over, or the browser tab was closed / navigated away):
        # always turn the webcam off so the Mac's green camera light goes out.
        is_recording = False
        release_camera(camera)
        camera = None

@height_bp.route('/')
def index():
    """Main page for Height & Weight estimation"""
    return render_template('height.html')

@height_bp.route('/start_camera', methods=['POST'])
def start_camera():
    """Start camera and initialize system"""
    global camera, is_recording, session_active, identity_error
    
    try:
        # Only the registered athlete, freshly face-verified, may start
        user_id, reference_photo, error, code = exercise_gate(session, get_db())
        if error:
            return jsonify(error), code
        identity_monitor.reset(user_id, reference_photo)

        # Always release existing camera first
        if camera is not None:
            camera.release()
            camera = None
        
        # Initialize camera
        camera = open_camera(1280, 720)
        if not camera.isOpened():
            return jsonify({'status': 'error', 'message': 'Camera unavailable'})
        
        is_recording = True
        session_active = True
        identity_error = False
        
        # Reset system state
        sys = get_system()
        sys.measurement_history = []
        sys.stability_buffer = []
        sys.consecutive_stable_frames = 0
        
        return jsonify({'status': 'success', 'message': 'Started'})
        
    except Exception as e:
        log_error(f"Error starting height camera: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@height_bp.route('/stop_camera', methods=['POST'])
def stop_camera():
    """Stop camera and cleanup"""
    global camera, is_recording, session_active
    
    try:
        is_recording = False
        session_active = False
        
        if camera:
            camera.release()
            camera = None
        
        return jsonify({'status': 'success', 'message': 'Stopped'})
    except Exception as e:
        log_error(f"Error stopping height camera: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@height_bp.route('/video_feed')
def video_feed():
    """Video stream endpoint"""
    log_info("Video feed request received")
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame',
                   headers={
                       'Cache-Control': 'no-cache, no-store, must-revalidate',
                       'Pragma': 'no-cache',
                       'Expires': '0'
                   })

@height_bp.route('/get_stats')
def get_stats():
    """Get current measurement stats"""
    from integrated_system import DetectionStatus
    sys = get_system()
    
    # Get latest result if available
    latest_result = None
    if sys.measurement_history:
        latest_result = sys.measurement_history[-1]
    
    stats = {
        'height': round(latest_result.height_cm, 1) if latest_result else 0,
        'weight': round(latest_result.weight_kg, 1) if latest_result else 0,
        'confidence': round(latest_result.confidence_score * 100, 1) if latest_result else 0,
        'status': latest_result.detection_status.value if latest_result else "Initializing",
        'message': latest_result.position_message if latest_result else "Connecting...",
        'is_stable': latest_result.detection_status == DetectionStatus.MEASURING_STABLE if latest_result else False,
        'is_auto_saved': latest_result.is_auto_saved if latest_result else False,
        'identity_error': identity_error or identity_monitor.terminated,
        'identity_status': identity_monitor.last_status
    }
    
    return jsonify(stats)
