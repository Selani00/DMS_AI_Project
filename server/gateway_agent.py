from flask import Blueprint, jsonify, request
import uuid
from core.agents import run_agent_workflow
import os

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Create if not exists

gateway_bp = Blueprint('gateway_bp', __name__)

# Endpoint 1: /api/tip
@gateway_bp.route('/api/tip', methods=['GET'])
def get_tip():
    tip_data = {
        "message": "Always comment your code!",
        "category": "Programming"
    }
    return jsonify(tip_data), 200

# Endpoint 2: /api/agent
@gateway_bp.route('/api/agent', methods=['POST'])
def agent_action():
    # For form-data text fields
    form_data = request.get_json()

    # # For uploaded files (optional)
    # image_file = request.files.get("image")
    # voice_file = request.files.get("voice")

    # image_path = None
    # if image_file:
    #     image_path = os.path.join(UPLOAD_FOLDER, image_file.filename)
    #     image_file.save(image_path)

    # voice_path = None
    # if voice_file:
    #     voice_path = os.path.join(UPLOAD_FOLDER, voice_file.filename)
    #     voice_file.save(voice_path)

    print(f"Form Data: {form_data}")
    # print(f"Image Path: {image_path}")
    # print(f"Voice Path: {voice_path}")

    # Build state for the workflow
    workflow_input = {
        "input": form_data,
    }

    workflow_result = run_agent_workflow(workflow_input)

    response_data = {
        "input": form_data.get("message"),
        "workflow_result": workflow_result,
        "status": "Agent action processed"
    }
    return jsonify(response_data), 201


    # data = request.get_json()
    # print(f"Received data: {data}")
    # if not data:
    #     return jsonify({"error": "Invalid request"}), 400
    
    # # if "task_id" not in data:
    # #     data["task_id"] = str(uuid.uuid4())
    
    # # Call the agent workflow
    # workflow_result = run_agent_workflow(data)

    # response_data = {
    #     # "task_id": data["task_id"],
    #     "input": data["message"],
    #     "workflow_result": workflow_result,
    #     "status": "Agent action processed"
    # }
    # return jsonify(response_data), 201
