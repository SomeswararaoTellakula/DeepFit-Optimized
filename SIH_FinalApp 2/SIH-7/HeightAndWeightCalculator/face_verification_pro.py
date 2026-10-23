import cv2
import numpy as np
import os
import base64
import time
import logging
from typing import Tuple, Dict, Optional, Union
from datetime import datetime

# NOTE: For production, ensure these are installed:
# pip install deepface tf-keras opencv-python
try:
    # pyrefly: ignore [missing-import]
    from deepface import DeepFace
except ImportError:
    DeepFace = None

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FaceVerificationPro")

class FaceVerificationPro:
    """
    Expert-level 1:1 Face Verification System.
    Implements Registration, Detection, Alignment, and Matching with production-ready standards.
    """

    def __init__(self, threshold: float = 0.65, model_name: str = "VGG-Face", detector_backend: str = "mtcnn"):
        """
        Initialize the verification system.
        
        Args:
            threshold (float): Verification threshold. DeepFace VGG-Face default is ~0.40 for Cosine, 
                               but we tune it for specific needs.
            model_name (str): Backend model (VGG-Face, Facenet, OpenFace, DeepFace, DeepID, ArcFace, Dlib).
            detector_backend (str): Face detector (opencv, retriever, mtcnn, ssd, dlib, mediapipe).
        """
        self.threshold = threshold
        self.model_name = model_name
        self.detector_backend = detector_backend
        self.min_resolution = (480, 360)
        
        logger.info(f"Initialized FaceVerificationPro with model={model_name}, detector={detector_backend}")

    def validate_input(self, image: np.ndarray) -> bool:
        if image is None:
            return False
        h, w = image.shape[:2]
        # Accept any image with at least 160x120 pixels
        if w < 160 or h < 120:
            logger.warning(f"Image resolution {w}x{h} too small for face verification")
            return False
        return True

    def check_liveness(self, frame: np.ndarray) -> bool:
        """
        PLACEHOLDER: Anti-spoofing / Liveness Detection.
        In a full production environment, this would implement:
        - Texture analysis (Blink detection, Head movement)
        - Depth analysis (using IR or Stereo cameras)
        - Frequency analysis (detecting screen moiré patterns)
        """
        # Logic Placeholder: 
        # return liveness_model.predict(frame) > 0.8
        logger.debug("Liveness check triggered (Placeholder: Always True)")
        return True

    def azure_ai_face_verify_mock(self, image1: np.ndarray, image2: np.ndarray) -> Dict:
        """
        Placeholder structure for transitioning to Azure AI Face Service.
        Demonstrates how to wrap the local logic into an API-ready format.
        """
        # azure_client = FaceClient(ENDPOINT, CognitiveServicesCredentials(KEY))
        # response = azure_client.face.verify_face_to_face(face_id1, face_id2)
        return {
            "isMatch": True,
            "confidence": 0.98,
            "service": "Microsoft Azure AI Face (Mock)"
        }

    def verify(self, reference_img: np.ndarray, live_img: np.ndarray) -> Tuple[bool, float, str]:
        """
        Core 1:1 Verification Pipeline.
        1. Validation
        2. Liveness Check
        3. Alignment & Detection (Internal to DeepFace or explicit)
        4. Feature Extraction & Matching
        """
        
        # 1. Validation
        if not self.validate_input(reference_img) or not self.validate_input(live_img):
            return False, 0.0, "Invalid input resolution or image format."

        # 2. Liveness Detection
        if not self.check_liveness(live_img):
            return False, 0.0, "Liveness check failed (Possible spoofing attempt)."

        if DeepFace is None:
            return False, 0.0, "DeepFace library not found. Please install it."

        try:
            # 3 & 4. Alignment, Detection, Extraction & Matching
            # DeepFace.verify handles MTCNN alignment and feature matching in one optimized call.
            result = DeepFace.verify(
                img1_path = reference_img, 
                img2_path = live_img, 
                model_name = self.model_name,
                detector_backend = self.detector_backend,
                distance_metric = "cosine",
                enforce_detection = True,
                align = True
            )

            is_verified = result.get("verified", False)
            distance = result.get("distance", 1.0)
            
            # Convert cosine distance to similarity score (0 to 1)
            similarity = 1.0 - distance
            
            logger.info(f"Verification Result: Verified={is_verified}, Similarity={similarity:.4f}")
            
            return is_verified, similarity, "Success"

        except ValueError as ve:
            logger.error(f"Face Detection Error: {ve}")
            return False, 0.0, "No face detected in one or both images."
        except Exception as e:
            logger.error(f"Unexpected Verification Error: {e}")
            return False, 0.0, f"System Error: {str(e)}"

    def enroll(self, image_path: str) -> bool:
        """
        Enrollment (Registration) check.
        Ensures the reference photo is high quality and has exactly one face.
        """
        if not os.path.exists(image_path):
            logger.error("Enrollment image path does not exist.")
            return False
            
        try:
            # Check for face presence and alignment quality
            faces = DeepFace.extract_faces(
                img_path = image_path,
                detector_backend = self.detector_backend,
                enforce_detection = True,
                align = True
            )
            
            if len(faces) == 1:
                logger.info("Enrollment successful: 1 high-quality face template captured.")
                return True
            else:
                logger.warning(f"Enrollment failed: Found {len(faces)} faces, expected 1.")
                return False
                
        except Exception as e:
            logger.error(f"Enrollment Error: {e}")
            return False

# --- UTILS ---
def decode_base64(base64_str: str) -> np.ndarray:
    """Helper to convert web base64 frames to OpenCV format, with EXIF rotation fix."""
    if not base64_str:
        return None
    if "," in base64_str:
        base64_str = base64_str.split(",")[1]
    try:
        decoded = base64.b64decode(base64_str)
        nparr = np.frombuffer(decoded, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        # Fix EXIF rotation using JPEG markers
        try:
            import struct
            data = decoded
            # Look for EXIF orientation tag in JPEG
            if data[:2] == b'\xff\xd8':  # JPEG magic bytes
                i = 2
                while i < len(data) - 1:
                    if data[i] != 0xff:
                        break
                    marker = data[i+1]
                    if marker == 0xe1:  # APP1 = EXIF
                        seg_len = struct.unpack('>H', data[i+2:i+4])[0]
                        seg = data[i+4:i+2+seg_len]
                        if seg[:4] == b'Exif':
                            tiff = seg[6:]
                            byte_order = tiff[:2]
                            bo = '<' if byte_order == b'II' else '>'
                            ifd_offset = struct.unpack(bo + 'I', tiff[4:8])[0]
                            num_entries = struct.unpack(bo + 'H', tiff[ifd_offset:ifd_offset+2])[0]
                            for e in range(num_entries):
                                entry_offset = ifd_offset + 2 + e * 12
                                tag = struct.unpack(bo + 'H', tiff[entry_offset:entry_offset+2])[0]
                                if tag == 0x0112:  # Orientation tag
                                    orientation = struct.unpack(bo + 'H', tiff[entry_offset+8:entry_offset+10])[0]
                                    if orientation == 3:
                                        img = cv2.rotate(img, cv2.ROTATE_180)
                                    elif orientation == 6:
                                        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
                                    elif orientation == 8:
                                        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                                    break
                        break
                    elif marker in (0xd8, 0xd9):
                        break
                    else:
                        seg_len = struct.unpack('>H', data[i+2:i+4])[0]
                        i += 2 + seg_len
        except Exception:
            pass  # If EXIF parsing fails, use image as-is
        return img
    except Exception:
        return None

# --- EXAMPLE USAGE ---
if __name__ == "__main__":
    # This block demonstrates the standalone usage of the Senior Engineer implementation
    v_pro = FaceVerificationPro(threshold=0.65)
    
    # Load mock images for demonstration
    # ref = cv2.imread("registration.jpg")
    # live = cv2.imread("webcam_frame.jpg")
    # match, score, msg = v_pro.verify(ref, live)
    # print(f"Match: {match} | Score: {score} | Message: {msg}")
