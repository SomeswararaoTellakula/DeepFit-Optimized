import cv2
import numpy as np
import mediapipe as mp
import base64
import logging
import os
from typing import Tuple, Dict, Optional, List
from face_verification_pro import FaceVerificationPro, decode_base64

# Configure Logging
logger = logging.getLogger("FaceVerifierUnified")

class FaceVerifier:
    """
    Unified Face Verification System for DeepFit.
    Expert implementation that bridges Mediapipe (fast/lightweight) 
    with DeepFace (high-accuracy/production) logic.
    """

    def __init__(self, threshold: float = 0.70):
        # 1. Initialize the High-End Professional Verifier (DeepFace)
        self.pro_verifier = FaceVerificationPro(threshold=threshold)
        
        # 2. Initialize Mediapipe as a high-speed fallback/alignment checker
        self.mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5
        )
        self.threshold = threshold
        
        # Landmarks for Mediapipe fallback signature
        self.LANDMARKS = {
            'left_eye_inner': 133, 'right_eye_inner': 263, 'nose_tip': 1, 'chin': 152
        }

    def decode_base64_image(self, base64_string: str) -> Optional[np.ndarray]:
        """Proxy to the pro decoder"""
        return decode_base64(base64_string)

    def get_face_signature(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Calculates a geometry-based signature using Mediapipe.
        Used as a high-speed orientation check or fallback.
        """
        if image is None: return None
        
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.mp_face_mesh.process(rgb)
        
        if not results.multi_face_landmarks:
            return None
            
        landmarks = results.multi_face_landmarks[0].landmark
        
        # Simple geometric signature for fallback
        def get_dist(p1, p2):
            return np.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)
            
        l_eye = landmarks[133]
        r_eye = landmarks[263]
        nose = landmarks[1]
        chin = landmarks[152]
        
        norm = get_dist(l_eye, r_eye) # Interpupillary distance
        if norm == 0: return None
        
        signature = [
            get_dist(l_eye, nose) / norm,
            get_dist(r_eye, nose) / norm,
            get_dist(nose, chin) / norm,
            get_dist(l_eye, chin) / norm
        ]
        return np.array(signature, dtype=np.float32)

    def compute_similarity(self, sig1: np.ndarray, sig2: np.ndarray) -> Tuple[float, float]:
        """Fallback geometric similarity"""
        dist = np.linalg.norm(sig1 - sig2)
        sim = max(0, 1.0 - (dist / 0.5))
        return sim, dist

    def verify(self, reference_photo_base64: str, current_frame: np.ndarray) -> Tuple[bool, float, Dict]:
        """
        Unified verify method.
        Attempts DeepFace verification first (if installed), 
        then falls back to high-speed Mediapipe geometry check.
        """
        debug_info = {
            'method': 'DeepFace (Production)',
            'resolution_ok': True,
            'face_detected': False
        }

        if current_frame is None:
            return False, 0.0, {'error': 'No frame provided'}

        # Flip webcam frame horizontally to match registration photo orientation
        current_frame = cv2.flip(current_frame, 1)

        # 1. Try Professional Verification (DeepFace)
        from face_verification_pro import DeepFace
        if DeepFace is not None:
            ref_img = self.decode_base64_image(reference_photo_base64)
            if ref_img is None:
                return False, 0.0, {'error': 'Failed to decode reference photo'}
            is_match, confidence, message = self.pro_verifier.verify(ref_img, current_frame)
            
            if "No face detected" not in message:
                debug_info['face_detected'] = True
                debug_info['similarity'] = confidence
                debug_info['message'] = message
                return is_match, confidence, debug_info

        # 2. Fallback to Mediapipe Geometry (Real-time speed)
        debug_info['method'] = 'Mediapipe Geometry (Fallback)'
        ref_img = self.decode_base64_image(reference_photo_base64)
        ref_sig = self.get_face_signature(ref_img)
        curr_sig = self.get_face_signature(current_frame)
        
        if ref_sig is not None and curr_sig is not None:
            debug_info['face_detected'] = True
            similarity, dist = self.compute_similarity(ref_sig, curr_sig)
            debug_info['similarity'] = similarity
            debug_info['distance'] = dist
            return similarity >= self.threshold, similarity, debug_info
            
        return False, 0.0, debug_info

    def verify_from_base64(self, reference_photo_base64: str, current_photo_base64: str) -> Tuple[bool, float, Dict]:
        curr_img = self.decode_base64_image(current_photo_base64)
        if curr_img is None:
            return False, 0.0, {'error': 'Decoding failed'}
        return self.verify(reference_photo_base64, curr_img)
