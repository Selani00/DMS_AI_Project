from langgraph.graph import StateGraph, END
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
import requests
import json
import os
import re
import threading
import base64
import datetime
from pathlib import Path

from db.db import change_status_after_assign_resources, resource_fetch, update_request_status, requests_fetch,assign_resources

load_dotenv()

QWEN_API_KEY = os.getenv("QWEN_API_KEY")
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # go 3 levels up from agents.py

class AgentState(BaseModel):
    input: Optional[Dict[str, Any]] = None
    image_path: Optional[str] = None
    voice_path: Optional[str] = None
    request: Optional[Dict[str, Any]] = None
    image_description: Optional[str] = None
    voice_description: Optional[str] = None
    status: Optional[str] = "pending"
    available_resources: Optional[List[Dict[str, Any]]] = None
    allocated_resources: Optional[dict] = None
    disaster_status: Optional[str] = "PENDING"
    user_msg:Optional[str]= None

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
    workflow.add_node("communicate_with_user", user_communication_agent)

    # Define flow
    workflow.set_entry_point("request_intake")
    workflow.add_edge("request_intake", "media_extraction")
    workflow.add_edge("media_extraction", "verify_request")
    workflow.add_edge("verify_request", "track_resources")
    workflow.add_edge("track_resources", "assign_resources")
    workflow.add_edge("assign_resources", "communicate_with_user")
    workflow.add_edge("communicate_with_user", END)

    return workflow.compile()


def resolve_media_path(raw_path: str) -> Path:
    # normalize slashes
    raw_path = raw_path.replace("\\", "/")
    # join with PROJECT_ROOT
    full_path = PROJECT_ROOT / raw_path
    return full_path.resolve()



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


# # Agent node implementations
# def request_intake_agent(state: AgentState):
#     print(f"Processing request intake: {state}")

#     prompt = f"""
#     You are an intelligent request intake agent.
#     Your role is to extract structured information from the following data regarding emergency or disaster-related events:

#     {state}

#     You must return the data in the following JSON format:
#     {{ 
#         "request_id": <int>,  
#         "disaster": "<string>",  
#         "disaster_id": <int>,  
#         "disaster_status": "low" | "medium" | "high" | "critical",  
#         "location": [<latitude>, <longitude>],
#         "affected_count": <int>,  
#         "contact_info": "<string>",  
#         "image_path": "<string>", 
#         "voice_path": "<string>",
#         "text_description": "<string>"
#     }}

#     Rules:
#     - If any field is not available in the input, use "Not applicable" or null as appropriate.
#     - Return ONLY the JSON object, no explanations.
#     """

 
#     try:
#         # Send request to local LLM API
#         res = requests.post(
#             "https://e037d0b95762.ngrok-free.app/api/generate",
#             headers={"Content-Type": "application/json"},
#             json={
#                 "model": "qwen3:4b",
#                 "prompt": prompt,
#                 "stream": False,
#                 "options": {"temperature": 0.2}
#             },
#             # timeout=30
#         )
#         res.raise_for_status()

#         # The model should return JSON text, parse it
#         model_output = res.text.strip()
#         try:
#             parsed_output = json.loads(model_output)
            
#         except json.JSONDecodeError:
#             print("⚠️ Model output is not valid JSON:", model_output)
#             parsed_output = {}

#         response_text = parsed_output.get("response", "")
#         text_test = parse_workflow_response(response_text)

#         print(f"Model output: {text_test}")

#         # Update state fields
#         if isinstance(text_test, dict):
#             state.image_path = text_test.get("image_path", None)
#             state.voice_path = text_test.get("voice_path", None)
#             state.request = text_test


#     except requests.RequestException as e:
#         print(f"❌ Error calling LLM API: {e}")

#     return state

def request_intake_agent(state: AgentState):
    print(f"Processing request intake: {state}")
    
    # Extract the input message from the state
    input_message = state.input['message'] if hasattr(state, 'input') and isinstance(state.input, dict) else str(state)
    
    # Helper function to extract values using regex
    def extract(pattern, default=None):
        match = re.search(pattern, input_message, re.IGNORECASE)
        return match.group(1).strip() if match else default

    # Extract all required fields
    request_id = extract(r'Request Id: (\d+)', None)
    disaster = extract(r'Disaster: (.+)', "Not applicable")
    disaster_id = extract(r'Disaster ID: (\d+)', None)
    severity_match = extract(r'Severity: (.+)', '').lower()
    disaster_status = (
        'critical' if 'critical' in severity_match else
        'high' if 'high' in severity_match else
        'medium' if 'medium' in severity_match else
        'low' if 'low' in severity_match else
        'Not applicable'
    )
    loc_match = re.search(r'Latitude ([\d.]+), Longitude ([\d.]+)', input_message, re.IGNORECASE)
    location = [float(loc_match.group(1)), float(loc_match.group(2))] if loc_match else [0.0, 0.0]
    affected_count = extract(r'Affected Count: (\d+)', 0)
    contact_info = extract(r'Contact No: (.+)', "Not applicable")
    image_path = extract(r'Image_path: (.+)', None)
    voice_path = extract(r'Voice_path: (.+)', None)
    text_description = extract(r'Details: (.+)', "Not applicable")

    # Build the response JSON
    response_json = {
        "request_id": int(request_id) if request_id else None,
        "disaster": disaster,
        "disaster_id": int(disaster_id) if disaster_id else None,
        "disaster_status": disaster_status,
        "location": location,
        "affected_count": int(affected_count) if affected_count else 0,
        "contact_info": contact_info,
        "image_path": image_path,
        "voice_path": voice_path,
        "text_description": text_description
    }

    # Update state fields
    state.image_path = image_path
    state.voice_path = voice_path
    state.request = response_json

    return state


def media_extraction_agent(state: AgentState):
    print("Extracting media descriptions...")

    def process_image():
        if state.image_path:
            try:
                resolved_path = resolve_media_path(state.image_path)
                print(f"Resolved path: {resolved_path}")

                if not resolved_path.exists():
                    print(f"⚠️ File not found at: {resolved_path}")
                    state.request["image_description"] = "Not applicable"
                    return
                
                with open(resolved_path, "rb") as img_file:
                    image_bytes = img_file.read()
                    image_b64 = base64.b64encode(image_bytes).decode("utf-8")  # ✅ Encode
                res = requests.post(
                    "https://e037d0b95762.ngrok-free.app/api/generate",
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

    # Get all the disaster which has same details
    res = requests_fetch(state.request.get("location", [0,0]),state.request.get("disaster_id",0))
    # Get number of previous requests
    no_of_previous_requests = len(res.get("disaster_data", []))

    if no_of_previous_requests >=5:
        state.status = "verified"
        update_request_status(state.request.get("request_id"), "verified")
        print("Request verified because it has 5 or more similar previous requests.")
        return state

    print(f"Number of previous requests: {no_of_previous_requests}")

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
                "https://e037d0b95762.ngrok-free.app/api/generate",
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

        if status_res.get('status') == "verified":
            # Implement the function to update the database with the verified status
            update_request_status(state.request.get("request_id"), "verified")

        state.status = status_res.get('status', '').strip()


    except requests.RequestException as e:
        print(f"❌ Error calling LLM API: {e}")

    return state

def resource_tracking_agent(state: AgentState):
    print("Tracking resources...")

    try:
        request_id = state.request.get("request_id",None)

        print(f"Fetching resources for request_id: {request_id}")

        res = resource_fetch(request_id)

        if res.get("status") != "success":
            print(f"⚠️ Resource fetch failed: {res.get('error', 'Unknown error')}")
            state.available_resources = {}
            return state

        all_available_resources = res.get("resources", [])
        print("Available resources:", all_available_resources)

        state.available_resources = all_available_resources

        # Parse the data to the LLM to  select most suitable resource for the mentioned disaster.
    except Exception as e:
        print(f"⚠️ Resource tracking error: {e}")

    return state

def resource_assign_agent(state: AgentState):
    print("Assigning resources...")

    PROMPT = f"""
    You are an intelligent resource assignment agent.
    Your task is to allocate the available resources from {state.available_resources} to the disaster request {state.request}.
    RULES:
    
    
    In the available resources
            - count means all the resources at that center
            - used means already allocated resources
            - resourceId mean resource center id

    Then you need to analyze the resource allocation and make decisions based on the available data. 
    Give the output in the following format:
    {{
        "request_id": "<id>", id from state.request
        "resource_center_ids": [<list of resource center ids which can assign to this request>],
        "quantities": [<list of quantities corresponding to each resource center id>]
    }}

    Rules:
    Assign resources to disaster requests by evaluating available quantities from resource centers. You must ensure:
            - No over-allocation (never assign more than is available)
            - Prioritized assignment based on proximity and resource availability
            - Each resource assignment marks the quantity as allocated
    """

    try:
        res = requests.post(
                "https://e037d0b95762.ngrok-free.app/api/generate",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "qwen3:4b",
                    "prompt": PROMPT,
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
        res_clear = parse_workflow_response(response_text)
        print(f"Allocation Resource: {res_clear}")

        # Save the allocation results to the database
        if res_clear:
            response = assign_resources(res_clear.get("request_id"),res_clear.get("resource_center_ids",[]),res_clear.get("quantities",[]))
            if response.get("status") == "success":
                state.allocated_resources = res_clear
                print("Resource allocation successful.")
                print(res_clear.get("request_id"))
                get_status = change_status_after_assign_resources(res_clear.get("request_id"), "success")
                print(f"Status change result: {get_status.get('status')}")
                # Update the state with the new status
                state.disaster_status = get_status.get('status')

    except requests.RequestException as e:
        print(f"❌ Error calling LLM API: {e}")

    return state


def user_communication_agent(state: AgentState):
    print("Communicating with user...")

    PROMPT = f"""
        You are an intelligent user communication agent. 
        Your task is to create a short and clear message that can be sent to the user about their disaster request.

        Information you have:
        - Request details: {state.request}
        - Verification status: {state.status}
        - Allocated resources: {state.allocated_resources}
        - Disaster severity/status: {state.disaster_status}

        Rules for generating the message:
        1. Always include a kind and motivating/encouraging sentence at the start (to keep the user hopeful and calm).
        2. If the request is VERIFIED → acknowledge and confirm to the user.
        If the request is NOT VERIFIED → politely explain that it cannot be verified right now, and mention that an agent will connect with them soon. 
        Encourage the user to re-send the request if the situation worsens.
        3. If resources are allocated → confirm to the user that help/resources are on the way.
        If no resources are allocated → explain that currently resources are limited, but reassure them that help will reach soon.
        4. Mention the disaster severity/status clearly so the user knows how serious the situation is.
        5. The message should be short, simple, and easy to understand by anyone (avoid technical jargon).

        Now, based on the above rules and given information, write one clear and supportive message for the user.
        """
    
    try:
        res = requests.post(
                "https://e037d0b95762.ngrok-free.app/api/generate",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "qwen3:4b",
                    "prompt": PROMPT,
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
        res_clear = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        print(f"User MSG: {res_clear}")

        # Save the allocation results to the database
        state.user_msg = res_clear

    except requests.RequestException as e:
        print(f"❌ Error calling LLM API: {e}")

    return state

