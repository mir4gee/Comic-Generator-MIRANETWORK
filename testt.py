from mira_sdk import MiraClient, CompoundFlow
from mira_sdk.exceptions import FlowError
import json

client = MiraClient(config={"API_KEY": "sb-9c307773dcea9649fb947457ba4d23c9"})     # Initialize Mira Client
flow = CompoundFlow(source="/home/mir4ge/Desktop/mira_net_/compound.yaml")           # Load flow configuration

input_dict = {
    "charactar1_emotion": "happy",
    "charactar1_age": "30",
    "charactar1_gender": "Man",
    "charactar1_hair_color": "brown",
    "charactar1_hairstyle": "short",
    "charactar1_face_shape": "oval",
    "charactar1_eyes": "almond",
    "charactar1_nose": "straight",
    "charactar1_lips": "full",
    "charactar1_ears": "visible",
    "charactar1_forehead": "average",
    "charactar1_neck": "average-length",
    "charactar1_jawline_length": "245.5",
    "charactar1_cheekbone_width": "240.7",
    "charactar1_mouth_width": "95.2",
    "charactar1_nose_width": "57.3",
    "charactar1_nose_length": "73.6",
    "charactar1_chin_type": "rounded",
    "charactar1_lip_fullness": "medium",
    "charactar1_lip_shape": "bow-shaped",
    "charactar1_teeth_visibility": "partial",
    "charactar1_eye_distance": "152.4",
    "charactar1_eye_shape": "round",
    "charactar1_eye_size": "medium",
    "charactar1_eyebrow_position": "medium",
    "charactar1_eyebrow_shape": "straight",
    "charactar1_forehead_height": "medium",
    "charactar1_skin_tone": "light",
    "charactar1_skin_texture": "smooth",
    "charactar1_freckles": "few",
    "charactar1_moles": "some",

    "charactar2_emotion": "curious",
    "charactar2_age": "25",
    "charactar2_gender": "Woman",
    "charactar2_hair_color": "black",
    "charactar2_hairstyle": "long",
    "charactar2_face_shape": "heart",
    "charactar2_eyes": "round",
    "charactar2_nose": "small",
    "charactar2_lips": "thin",
    "charactar2_ears": "not visible",
    "charactar2_forehead": "high",
    "charactar2_neck": "long",
    "charactar2_jawline_length": "235.8",
    "charactar2_cheekbone_width": "230.4",
    "charactar2_mouth_width": "90.1",
    "charactar2_nose_width": "55.7",
    "charactar2_nose_length": "70.2",
    "charactar2_chin_type": "pointed",
    "charactar2_lip_fullness": "thin",
    "charactar2_lip_shape": "straight",
    "charactar2_teeth_visibility": "visible",
    "charactar2_eye_distance": "149.6",
    "charactar2_eye_shape": "almond",
    "charactar2_eye_size": "large",
    "charactar2_eyebrow_position": "high",
    "charactar2_eyebrow_shape": "arched",
    "charactar2_forehead_height": "high",
    "charactar2_skin_tone": "medium",
    "charactar2_skin_texture": "slightly rough",
    "charactar2_freckles": "none",
    "charactar2_moles": "none",

    "conversation": "charactar 1: Hello! How are you?\ncharactar 2: I'm great, thanks for asking. What about you?"
}



try:
    response = client.flow.test(flow, input_dict)           # Test entire pipeline
    pretty_json = json.dumps(response, indent=4)
    print()
    print()
    print()
    print()
    print(pretty_json)
    
    print("Test response:", response)
except FlowError as e:
    print("Test failed:", str(e))                           # Handle test failure
