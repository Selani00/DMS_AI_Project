from langgraph.graph import StateGraph, END
from pydantic import BaseModel
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import requests
import json
import os
import re
import threading
import base64

load_dotenv()

QWEN_API_KEY = os.getenv("QWEN_API_KEY")

class AgentState(BaseModel):
    message: Optional[Dict[str, Any]] = None
    image_path: Optional[str] = None
    voice_path: Optional[str] = None
    request: Optional[Dict[str, Any]] = None
    image_description: Optional[str] = None
    voice_description: Optional[str] = None
    status: Optional[str] = "pending"

def run_agent_workflow(input_data: str):
    initial_state = AgentState(**input_data)
    agent_workflow = create_workflow()
    config = {"recursion_limit": 100} 
    return agent_workflow.invoke(initial_state, config=config)

def create_workflow():
    workflow = StateGraph(AgentState)
    workflow.add_node("request_intake", request_intake_agent)
    workflow.add_node("media_extraction", media_extraction_agent)  
    workflow.add_node("verify_request", request_verify_agent)
    workflow.add_node("track_resources", resource_tracking_agent)
    workflow.add_node("assign_resources", resource_assign_agent)
    workflow.add_node("communicate_with_first_responder", first_responder_communication_agent)
    workflow.add_node("communicate_with_user", user_communication_agent)

    # Define flow
    workflow.set_entry_point("request_intake")
    workflow.add_edge("request_intake", "media_extraction")  # add here
    workflow.add_edge("media_extraction", "verify_request")
    # workflow.add_edge("request_intake", "verify_request")
    workflow.add_edge("verify_request", "track_resources")
    workflow.add_edge("track_resources", "assign_resources")
    workflow.add_edge("assign_resources", "communicate_with_first_responder")
    workflow.add_edge("communicate_with_first_responder", "communicate_with_user")
    workflow.add_edge("communicate_with_user", END)

    return workflow.compile()


# def parse_workflow_response(workflow_result):
#     """
#     Extracts JSON from workflow_result['request']['response'],
#     removes <think> tags, and handles imperfect JSON gracefully.
#     """
#     response_text = workflow_result.get("request", {}).get("response", "")
#     # Remove <think> tags
#     response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
#     print("Cleaned response text:", response_text)

#     # Try to find JSON block
#     json_match = re.search(r'(\{.*\})', response_text, flags=re.DOTALL)
#     if not json_match:
#         return {}  # No JSON found

#     json_text = json_match.group(1)

#     # Attempt JSON parsing
#     try:
#         return json.loads(json_text)
#     except json.JSONDecodeError:
#         # Try common fixes for LLM JSON errors
#         fixed = json_text.replace("'", '"')  # Replace single quotes with double quotes
#         fixed = re.sub(r",\s*}", "}", fixed)  # Remove trailing commas before }
#         fixed = re.sub(r",\s*]", "]", fixed)  # Remove trailing commas before ]
#         try:
#             return json.loads(fixed)
#         except Exception:
#             return {}  # Final fallback


def parse_workflow_response(response_text: str):
    # Remove <think> tags
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
    print("Cleaned response text:", response_text)

    # Try to find JSON block
    json_match = re.search(r'(\{.*\})', response_text, flags=re.DOTALL)
    if not json_match:
        return {}

    json_text = json_match.group(1)

    # Attempt JSON parsing
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        fixed = json_text.replace("'", '"')
        fixed = re.sub(r",\s*}", "}", fixed)
        fixed = re.sub(r",\s*]", "]", fixed)
        try:
            return json.loads(fixed)
        except Exception:
            return {}


# Agent node implementations
def request_intake_agent(state: AgentState):
    print(f"Processing request intake: {state}")

    prompt = f"""
    You are an intelligent request intake agent.
    Your role is to extract structured information from the following data regarding emergency or disaster-related events:

    {state}

    You must return the data in the following JSON format:
    {{ 
        "request_id": <int>,  
        "disaster": "<string>",  
        "disaster_id": <int>,  
        "disaster_status": "low" | "medium" | "high" | "critical",  
        "location": [<latitude>, <longitude>],  
        "time": "<ISO 8601 format>",  
        "affected_count": <int>,  
        "contact_info": "<string>",  
        "image_path": "<string>", 
        "voice_path": "<string>",
        "text_description": "<string>"
    }}

    Rules:
    - If any field is not available in the input, use "Not applicable" or null as appropriate.
    - Return ONLY the JSON object, no explanations.
    """

 
    try:
        # Send request to local LLM API
        res = requests.post(
            "https://d53cb0fd37cb.ngrok-free.app/api/generate",
            headers={"Content-Type": "application/json"},
            json={
                "model": "qwen3:4b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2}
            },
            # timeout=30
        )
        res.raise_for_status()

        # The model should return JSON text, parse it
        model_output = res.text.strip()
        try:
            parsed_output = json.loads(model_output)
            
        except json.JSONDecodeError:
            print("⚠️ Model output is not valid JSON:", model_output)
            parsed_output = {}

        response_text = parsed_output.get("response", "")
        print(f"Raw model output: {response_text}")

        text_test = parse_workflow_response(response_text)

        print(f"Model output: {text_test}")

        # Update state fields
        if isinstance(text_test, dict):
            state.image_path = text_test.get("image_path", None)
            state.voice_path = text_test.get("voice_path", None)
            state.request = text_test


    except requests.RequestException as e:
        print(f"❌ Error calling LLM API: {e}")

    return state


def media_extraction_agent(state: AgentState):
    print("Extracting media descriptions...")

    def process_image():
        if state.image_path:
            try:
                print("Processing image:", state.image_path)
                with open(state.image_path, "rb") as img_file:
                    image_bytes = img_file.read()
                    image_b64 = base64.b64encode(image_bytes).decode("utf-8")  # ✅ Encode
                res = requests.post(
                    "https://d53cb0fd37cb.ngrok-free.app/api/generate",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "llava:7b",
                        "prompt": "Describe the image in detail focusing on disaster context.",
                        "images": [image_b64],
                        "stream": False
                    }
                )
                res.raise_for_status()
                response_data = res.json()
                image_description = response_data.get('response', '').strip()
                print(f"Image description response: {image_description}")
                state.image_description = image_description
            except Exception as e:
                state.request["image_description"] = "Not applicable"
                print(f"⚠️ Image extraction error: {e}")

    # def process_voice():
    #     if state.voice_path:
    #         try:
    #             import whisper
    #             model = whisper.load_model("small")
    #             result = model.transcribe(state.voice_path)
    #             state.request["voice_description"] = result.get("text", "").strip() or "Not applicable"
    #         except Exception as e:
    #             state.request["voice_description"] = "Not applicable"
    #             print(f"⚠️ Voice extraction error: {e}")

    process_image()

    # # Run both in parallel
    # img_thread = threading.Thread(target=process_image)
    # # voice_thread = threading.Thread(target=process_voice)
    # img_thread.start()
    # # voice_thread.start()
    # img_thread.join()
    # # voice_thread.join()

    return state
   

def request_verify_agent(state: AgentState):
    print("Verifying request...")

    prompt = f"""
    You are an intelligent request verification agent.
    Your task is to use {state.request} , image_description: {state.image_description} ,voice_description: {state.voice_description} :
            1. Verify the disaster request information using disaster and text_description in {state.request} , image_description and voice_description.
            2. Update the status in to "pending", "verified", "invalid" as appropriate.

    Give the output in the following format:
    {{
        "status": "<status>",
    }}

    Rules:
    - If only one is available(image_description or text_description or voice_description) status is "pending".
    - If it has two or three and they are match with each other and disaster name, status is "verified".
    - If none of the above conditions are met, status is "invalid".
    """

    try:
        res = requests.post(
                "https://d53cb0fd37cb.ngrok-free.app/api/generate",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "qwen3:4b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2}
                },
            )
        res.raise_for_status()

        model_output = res.text.strip()
        try:
            parsed_output = json.loads(model_output)
                
        except json.JSONDecodeError:
                print("⚠️ Model output is not valid JSON:", model_output)
                parsed_output = {}

        response_text = parsed_output.get("response", "")
        status_res = parse_workflow_response(response_text)
        print(f"Status output: {status_res}")

        state.status = status_res.get('status', '').strip()

    except requests.RequestException as e:
        print(f"❌ Error calling LLM API: {e}")

    return state

def resource_tracking_agent(state: AgentState):
    print("Tracking resources...")
    return state

def resource_assign_agent(state: AgentState):
    print("Assigning resources...")
    return state

def first_responder_communication_agent(state: AgentState):
    print("Communicating with first responder...")
    return state

def user_communication_agent(state: AgentState):
    print("Communicating with user...")
    return state
