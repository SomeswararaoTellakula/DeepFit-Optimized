from flask import Blueprint, render_template, Response, jsonify, request, session
import cv2
import mediapipe as mp
import numpy as np
import threading
import time
import json
import os
from datetime import datetime
from pathlib import Path
from bson import ObjectId
from db_config import get_db
from advanced_jump_detector import AdvancedJumpDetector
from identity_guard import LiveIdentityMonitor, exercise_gate
from perf import open_camera, release_camera, FrameThrottle, encode_jpeg, mjpeg_chunk

vertical_jump_bp = Blueprint('vertical_jump', __name__,
                           template_folder='templates',
                           static_folder='static')

# Global variables
camera = None
is_recording = False
session_active = False
start_time = None
_jump_detector = None
# Re-checks the athlete's face every 2 s in a background thread during the exercise
identity_monitor = LiveIdentityMonitor(interval=2.0, max_strikes=3)


def get_jump_detector():
    """Create the pose model only when the jump page is actually used."""
    global _jump_detector
    if _jump_detector is None:
        _jump_detector = AdvancedJumpDetector()
    return _jump_detector
exercise_stats = {
    'total_jumps': 0,
    'current_height': 0.0,
    'max_height': 0.0,
    'state': 'GROUND',
    'calibrated': False,
    'feedback': 'System Ready',
    'identity_error': False
}

def get_current_user():
    try:
        db = get_db()
        if db and 'user_id' in session:
            user = db.users.find_one({'_id': ObjectId(session['user_id'])})
            if user:
                return {'email': user.get('email', 'user@example.com')}
        return {'email': 'test_user_001@example.com'}
    except:
        return {'email': 'test_user_001@example.com'}

def generate_frames():
    global camera, is_recording, exercise_stats
    detector = get_jump_detector()
    throttle = FrameThrottle(24)   # jumps are fast, keep a higher frame rate here
    try:
        while is_recording and camera is not None:
            success, frame = camera.read()
            if not success:
                time.sleep(0.05)
                continue

            identity_monitor.submit(frame)          # non-blocking background face check
            if identity_monitor.terminated:
                print("Jump: session stopped - a different person was detected")
                exercise_stats['identity_error'] = True
                is_recording = False
                break

            frame = detector.process_frame(frame)
            stats = detector.get_performance_stats()
            exercise_stats.update({
                'total_jumps': stats['total_jumps'],
                'current_height': stats['current_height'],
                'max_height': stats['max_height'],
                'state': stats['state'],
                'calibrated': stats['calibrated'],
                'feedback': stats['feedback']
            })
            identity_monitor.draw(frame)

            yield mjpeg_chunk(encode_jpeg(frame))
            throttle.wait()
    finally:
        # The stream ended (session over, or the browser tab was closed / navigated away):
        # always turn the webcam off so the Mac's green camera light goes out.
        is_recording = False
        release_camera(camera)
        camera = None

@vertical_jump_bp.route('/start_camera')
def start_camera():
    global camera, is_recording, session_active, start_time
    
    try:
        # Only the registered athlete, freshly face-verified, may start
        user_id, reference_photo, error, code = exercise_gate(session, get_db())
        if error:
            return jsonify(error), code
        identity_monitor.reset(user_id, reference_photo)

        if camera is not None:
            camera.release()
            camera = None
        
        camera = open_camera(640, 480)
        if not camera.isOpened():
            return jsonify({'status': 'error', 'message': 'Camera unavailable'})
        
        is_recording = True
        session_active = True
        start_time = time.time()
        exercise_stats['identity_error'] = False
        
        get_jump_detector().reset_session()
        
        return jsonify({'status': 'success', 'message': 'Started'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@vertical_jump_bp.route('/stop_camera')
def stop_camera():
    global camera, is_recording, session_active
    
    try:
        is_recording = False
        session_active = False
        
        if camera:
            camera.release()
            camera = None
        
        # Save to MongoDB
        try:
            db = get_db()
            if db:
                stats = get_jump_detector().get_performance_stats()
                duration = round(time.time() - start_time, 2) if start_time else 0
                
                # Prepare MongoDB session data
                user_oid = None
                if 'user_id' in session:
                    user_oid = ObjectId(session['user_id'])
                
                if user_oid:
                    try:
                        # Create session document for analysis route
                        session_doc = {
                            "user_id": user_oid,
                            "exercise_type": "vertical_jump",
                            "repetitions": int(stats['total_jumps']),
                            "duration": int(duration),
                            "date": datetime.utcnow()
                        }
                        session_result = db.exercise_sessions.insert_one(session_doc)
                        session_id = session_result.inserted_id
                        
                        # Create result document for analysis route
                        result_doc = {
                            "user_id": user_oid,
                            "session_id": session_id,
                            "exercise_type": "vertical_jump",
                            "repetitions": int(stats['total_jumps']),
                            "form_score": 88,
                            "duration": int(duration),
                            "range_of_motion": 85,
                            "speed_control": 90,
                            "form_feedback": f"Max height: {stats['max_height']:.1f}cm",
                            "timestamp": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
                        }
                        db.exercise_results.insert_one(result_doc)
                        print(f"✅ Vertical jump session and results saved to MongoDB")
                    except Exception as e:
                        print(f"Error saving vertical jump data to standard collections: {e}")
        except Exception as e:
            print(f"Error in vertical jump stop_camera: {e}")

        # Save to existing Vertical_Jump collection via detector
        get_jump_detector().save_to_mongodb()
        
        return jsonify({'status': 'success', 'message': 'Stopped'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@vertical_jump_bp.route('/reset_counter')
def reset_counter():
    global exercise_stats, session_active, camera, is_recording
    
    try:
        if is_recording:
            is_recording = False
        
        if camera is not None:
            camera.release()
            camera = None
        
        session_active = False
        get_jump_detector().reset_session()
        
        exercise_stats.update({
            'total_jumps': 0,
            'current_height': 0.0,
            'max_height': 0.0,
            'state': 'GROUND',
            'calibrated': False,
            'feedback': 'System Ready'
        })
        
        return jsonify({'status': 'success', 'message': 'Reset'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@vertical_jump_bp.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@vertical_jump_bp.route('/get_stats')
def get_stats():
    if is_recording:
        stats = get_jump_detector().get_performance_stats()
        exercise_stats.update({
            'total_jumps': stats['total_jumps'],
            'current_height': stats['current_height'],
            'max_height': stats['max_height'],
            'state': stats['state'],
            'calibrated': stats['calibrated'],
            'feedback': stats['feedback']
        })
    exercise_stats.update(identity_monitor.status())
    return jsonify(exercise_stats)

@vertical_jump_bp.route('/cleanup', methods=['POST'])
def cleanup():
    global camera, is_recording, session_active
    
    try:
        is_recording = False
        session_active = False
        
        if camera is not None:
            camera.release()
            camera = None
        
        return '', 204
    except Exception:
        return '', 204