import cv2
import numpy as np
import dlib
import tensorflow as tf
from deepface import DeepFace
from sklearn.cluster import KMeans
from imutils import face_utils
# Load Dlib's pre-trained shape predictor model
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor("/home/rohit/Downloads/shape_predictor_68_face_landmarks.dat")
def analyze_face(image_path):
    img = cv2.imread(image_path)
    
    # Analyze face using DeepFace
    try:
        analysis = DeepFace.analyze(img, actions=['emotion', 'age', 'gender'], enforce_detection=True)
    except Exception as e:
        return f"Error in face analysis: {e}"
    
    # Handle list or dictionary result
    if isinstance(analysis, list):
        analysis = analysis[0]  # Take the first detected face
    
    # Extract face analysis details
    emotion = analysis.get('dominant_emotion', 'Unknown')
    age = analysis.get('age', 'Unknown')
    gender = analysis.get('gender', 'Unknown')
    
    return {
        "emotion": emotion,
        "age": age,
        "gender": gender
    }

def extract_hair_details(image_path):
    # Load image
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Image file not found at {image_path}. Please check the file path.")
    
    # Convert BGR to RGB
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    # Convert to LAB color space for better color segmentation
    lab_img = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    img_reshaped = lab_img.reshape((-1, 3))
    
    # Use KMeans clustering for dominant hair color
    kmeans = KMeans(n_clusters=3, random_state=0).fit(img_reshaped)
    dominant_colors = kmeans.cluster_centers_
    
    # Assume hair color is the darkest dominant color
    dominant_colors = sorted(dominant_colors, key=lambda x: sum(x))  # Sort by brightness
    hair_color = dominant_colors[0]  # Darkest color
    hair_color = [int(c) for c in hair_color]
    
    # Map color to human-readable name
    hair_color_name = map_color_to_name(hair_color)
    hairstyle = "wavy"  # Placeholder for hairstyle analysis
    
    return {
        "hair_color": hair_color_name,
        "hairstyle": hairstyle
    }

def map_color_to_name(rgb):
    if rgb[0] < 60 and rgb[1] < 60 and rgb[2] < 60:
        return "black"
    elif rgb[0] > 200 and rgb[1] > 180:
        return "blonde"
    elif 80 < rgb[0] < 150 and 50 < rgb[1] < 100:
        return "brown"
    else:
        return "red"

def analyze_eyebrow_position(landmarks):
    # Average y-coordinates for the eyebrows and eyes
    left_brow_y = np.mean([landmarks[i][1] for i in range(17, 22)])
    right_brow_y = np.mean([landmarks[i][1] for i in range(22, 27)])
    left_eye_y = np.mean([landmarks[i][1] for i in range(36, 42)])
    right_eye_y = np.mean([landmarks[i][1] for i in range(42, 48)])
    
    # Relative height of eyebrows compared to eyes
    left_diff = left_brow_y - left_eye_y
    right_diff = right_brow_y - right_eye_y
    
    # Categorize position
    if left_diff > 20 and right_diff > 20:
        return "high"
    elif left_diff < 10 and right_diff < 10:
        return "low"
    else:
        return "neutral"


def analyze_facial_structure(image_path):
    # Load image
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Detect faces and landmarks
    faces = detector(gray)
    if not faces:
        return "No face detected."
    
    face_features = {}
    for face in faces:
        shape = predictor(gray, face)
        
        # Convert landmarks to a list of (x, y) coordinates
        landmarks = np.array([[shape.part(i).x, shape.part(i).y] for i in range(68)])
        
        # Analyze features
        face_features = {
            "face_shape": determine_face_shape(landmarks),
            "eyes": analyze_eyes(landmarks),
            "nose": analyze_nose(landmarks),
            "lips": analyze_lips(landmarks),
            "ears": "visible" if landmarks[1][0] - landmarks[0][0] > 5 else "not visible",
            "forehead": "broad" if landmarks[16][0] - landmarks[0][0] > landmarks[8][1] - landmarks[19][1] else "narrow",
            "neck": "average-length",  # Placeholder; requires full-body image
            "jawline_length": np.linalg.norm(landmarks[0] - landmarks[16]),
            "cheekbone_width": np.linalg.norm(landmarks[1] - landmarks[15]),
            "mouth_width": np.linalg.norm(landmarks[54] - landmarks[48]),
            "nose_width": np.linalg.norm(landmarks[31] - landmarks[35]),
            "nose_length": np.linalg.norm(landmarks[27] - landmarks[33]),
            "chin_type": "pointed" if np.linalg.norm(landmarks[8] - landmarks[5]) > 70 else "rounded",
            "lip_fullness": "full" if np.linalg.norm(landmarks[50] - landmarks[52]) > np.linalg.norm(landmarks[57] - landmarks[59]) else "thin",
            "lip_shape": "bow-shaped" if np.linalg.norm(landmarks[48] - landmarks[54]) > 70 else "straight",
            "teeth_visibility": "visible" if np.linalg.norm(landmarks[62] - landmarks[66]) > 10 else "not visible",
            "eye_distance": np.linalg.norm(landmarks[36] - landmarks[45]),
            "eye_shape": "round" if np.linalg.norm(landmarks[36] - landmarks[39]) < np.linalg.norm(landmarks[36] - landmarks[45]) / 2 else "almond",
            "eye_size": "large" if np.linalg.norm(landmarks[36] - landmarks[45]) > 100 else "medium" if np.linalg.norm(landmarks[36] - landmarks[45]) > 60 else "small",
"eyebrow_position": analyze_eyebrow_position(landmarks),
                        "eyebrow_shape": analyze_eyebrow_shape(landmarks),
            "forehead_height": analyze_forehead_height(landmarks),
            "skin_tone": analyze_skin_tone(img, landmarks),
            "skin_texture": analyze_skin_texture(img, landmarks),
            "freckles": detect_freckles(img, landmarks),
            "moles": detect_moles(img, landmarks)
        }
    return face_features

def determine_face_shape(landmarks):
    jaw_width = np.linalg.norm(landmarks[16] - landmarks[0])
    face_height = np.linalg.norm(landmarks[8] - landmarks[27])
    cheekbone_width = np.linalg.norm(landmarks[15] - landmarks[1])
    
    if face_height / jaw_width > 1.5:
        return "oval"
    elif cheekbone_width / face_height > 0.8:
        return "round"
    elif jaw_width / cheekbone_width > 1.2:
        return "square"
    else:
        return "heart-shaped"

def analyze_eyes(landmarks):
    left_eye = landmarks[36:42]
    right_eye = landmarks[42:48]
    left_width = np.linalg.norm(left_eye[3] - left_eye[0])
    left_height = np.linalg.norm(left_eye[1] - left_eye[5])
    eye_shape = "almond" if left_width > left_height * 2 else "round"
    return eye_shape

def analyze_nose(landmarks):
    nose_width = np.linalg.norm(landmarks[31] - landmarks[35])
    nose_length = np.linalg.norm(landmarks[27] - landmarks[33])
    return "long" if nose_length > nose_width else "short"

def analyze_lips(landmarks):
    lip_width = np.linalg.norm(landmarks[54] - landmarks[48])
    lip_height = np.linalg.norm(landmarks[62] - landmarks[66])
    return "full" if lip_height > lip_width / 4 else "thin"

def analyze_eyebrow_shape(landmarks):
    left_brow = landmarks[17:22]
    right_brow = landmarks[22:27]
    curvature = lambda brow: np.max(np.diff(brow[:, 1]))  # Vertical differences
    if curvature(left_brow) > 5 or curvature(right_brow) > 5:
        return "arched"
    return "straight"

def analyze_forehead_height(landmarks):
    forehead_height = landmarks[19][1] - landmarks[27][1]
    return "high" if forehead_height > 50 else "medium" if forehead_height > 30 else "low"

def analyze_skin_tone(image, landmarks):
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(landmarks[0:27]), 255)
    skin_region = cv2.bitwise_and(image, image, mask=mask)
    lab_skin = cv2.cvtColor(skin_region, cv2.COLOR_BGR2LAB)
    mean_color = np.mean(lab_skin, axis=(0, 1))
    if mean_color[0] < 70:
        return "dark"
    elif mean_color[0] < 140:
        return "medium"
    return "light"

def analyze_skin_texture(image, landmarks):
    skin_region = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    texture_score = cv2.Laplacian(skin_region, cv2.CV_64F).var()
    return "smooth" if texture_score < 100 else "rough"

def detect_freckles(image, landmarks):
    skin_region = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(skin_region, (5, 5), 0)
    _, binary = cv2.threshold(blur, 100, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    freckles_count = len([c for c in contours if cv2.contourArea(c) < 50])
    return "many" if freckles_count > 10 else "few" if freckles_count > 3 else "none"

def detect_moles(image, landmarks):
    skin_region = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.medianBlur(skin_region, 5)
    circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=20, param1=50, param2=30, minRadius=1, maxRadius=5)
    return len(circles[0]) if circles is not None else "none"

def generate_description(image_path):
    face_details = analyze_face(image_path)
    hair_details = extract_hair_details(image_path)
    facial_structure = analyze_facial_structure(image_path)
    # print(face_details)
    # print(hair_details)
    # print(facial_structure)
    description = (
        f"The person has {hair_details['hairstyle']} {hair_details['hair_color']} hair. "
        f"Their face shape is {facial_structure['face_shape']}. "
        f"They have {facial_structure['eyes']} eyes, a {facial_structure['nose']} nose, and {facial_structure['lips']} lips. "
        f"Their ears are {facial_structure['ears']}, and their forehead is {facial_structure['forehead']}. "
        f"Their jawline length is {facial_structure['jawline_length']:.2f}, cheekbone width is {facial_structure['cheekbone_width']:.2f}, and mouth width is {facial_structure['mouth_width']:.2f}. "
        f"They appear to be {face_details['age']} years old, identify as {face_details['gender']}, and their dominant emotion is {face_details['emotion']}. "
        f"Additional features: {facial_structure['eye_shape']} eyes, {facial_structure['lip_fullness']} lips, {facial_structure['skin_tone']} skin tone, and {facial_structure['skin_texture']} texture."
    )
    return description

# Replace 'your_image_path.jpg' with the path to your image
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[""],  # Allow all origins (replace "" with specific origins like ["http://127.0.0.1:5500"] if needed)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all HTTP headers
)

@app.post("/process_image")
async def process_image(file: UploadFile = File(...)):
    try:
        # Save the uploaded file
        file_path = f"./uploaded_images/{file.filename}"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(await file.read())

        # Mock image processing and description generation
        description = f"Processed description for {file.filename}"
        return {"description": description}

    except Exception as e:
        return {"error": str(e)}, 500