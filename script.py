from flask import Flask, request, jsonify
from flask_cors import CORS
import cv2
import numpy as np
import pytesseract
import base64

app = Flask(_name_)
CORS(app)  # Allow cross-origin requests for development

# Helper function to detect text regions
def detect_text_regions(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bounding_boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w > 30 and h > 10:  # Filter small regions
            bounding_boxes.append((x, y, w, h))
    return bounding_boxes

# Helper function to get dominant color
def get_dominant_color(image, box):
    x, y, w, h = box
    roi = image[y:y+h, x:x+w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0], None, [180], [0, 180])
    dominant_hue = np.argmax(hist)
    return dominant_hue

# Helper function to classify speaker
def classify_speaker(dominant_hue):
    if 0 <= dominant_hue <= 30 or 150 <= dominant_hue <= 180:  # Red
        return "Speaker 1"
    elif 90 <= dominant_hue <= 150:  # Blue/Green
        return "Speaker 2"
    else:
        return "Unknown"

# Main route to process uploaded image
@app.route('/process-image', methods=['POST'])
def process_image():
    try:
        data = request.json
        image_data = data['image']
        image_data = base64.b64decode(image_data.split(',')[1])
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Detect text regions
        bounding_boxes = detect_text_regions(image)

        # Extract text using Tesseract
        ocr_text = pytesseract.image_to_string(image)
        ocr_lines = ocr_text.splitlines()

        speakers = []
        for box, text in zip(bounding_boxes, ocr_lines):
            if text.strip():  # Ignore empty lines
                dominant_hue = get_dominant_color(image, box)
                speaker = classify_speaker(dominant_hue)
                speakers.append(f"{speaker}: {text}")

        return jsonify({'status': 'success', 'result': '\n'.join(speakers)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if _name_ == '_main_':
    app.run(debug=True)