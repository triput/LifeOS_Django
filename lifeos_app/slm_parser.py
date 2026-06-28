# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/slm_parser.py
# Description: Small Language Model constraint parser client
# Component: Core / Inference Engine
# Version: 1.0 (Gold Master)
# Created: 2026-06-27
# Last Update: 2026-06-27
# ==============================================================================

import json
import requests
from .models import AppSettings

class SLMParseError(Exception):
    """Exception raised when the SLM fails to parse or respond."""
    pass

def parse_natural_language_constraints(text: str) -> dict:
    """
    Parses natural language into a structured JSON dictionary of scheduling constraints
    using the configured SLM provider.
    
    Returns a dictionary matching the constraint schema.
    """
    app_settings = AppSettings.get_solo()
    
    if app_settings.slm_provider == 'Skip':
        raise SLMParseError("SLM parsing is currently disabled (Provider set to 'Skip' in Settings).")
        
    from django.utils import timezone
    import datetime
    
    now = timezone.now()
    current_date = now.date().isoformat()
    current_day = now.strftime("%A")
    
    # Generate a 7-day lookup dictionary to assist the SLM in calendar mapping
    days_context = []
    for i in range(7):
        d = now + datetime.timedelta(days=i)
        days_context.append(f"{d.strftime('%A')}: {d.date().isoformat()}")
    days_context_str = ", ".join(days_context)
    
    system_prompt = f"""
    You are an intelligent scheduling assistant. Extract scheduling constraints from the user's input.
    The current date is {current_date} ({current_day}).
    Upcoming days reference: {days_context_str}.
    Use this lookup table context to map day names (like "Tuesday") directly to their absolute YYYY-MM-DD dates.
    Return ONLY a valid JSON object matching this exact schema without any markdown blocks or conversational text.
    
    Schema:
    {{
      "title": "Clean, concise name of the task (e.g. 'Hair with Holly'), stripping out verbs like 'schedule' or details like dates, times, and priorities",
      "duration_minutes": integer or null (estimate time if not provided, default 30),
      "priority": "Low" | "Medium" | "High" | "Critical" or null,
      "urgency": "Low" | "Normal" | "High" | "Immediate" or null,
      "target_date": "YYYY-MM-DD" or null (if user mentions a specific day),
      "time_of_day": "morning" | "afternoon" | "evening" | null
    }}
    """
    
    if app_settings.slm_provider == 'Local Ollama':
        url = app_settings.slm_endpoint
        if not url.endswith('/api/generate'):
            url = url.rstrip('/') + '/api/generate'
            
        payload = {
            "model": "llama3", # Defaulting to llama3, could be made dynamic later
            "prompt": f"{system_prompt}\n\nUser Input: {text}\n\nOutput:",
            "stream": False,
            "format": "json"
        }
        
        try:
            headers = {}
            import os
            api_key = os.environ.get('SLM_API_KEY')
            if api_key:
                headers['Authorization'] = f"Bearer {api_key}"
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            raw_response = data.get('response', '{}')
            return json.loads(raw_response)
            
        except requests.exceptions.RequestException as e:
            raise SLMParseError(f"Connection failed to Ollama at {url}. Make sure Ollama is running. ({e})")
        except json.JSONDecodeError:
            raise SLMParseError(f"SLM returned invalid JSON. Raw output: {raw_response}")
            
    elif app_settings.slm_provider == 'Cloud API':
        # Stub for future OpenAI/Anthropic/Google Cloud integration
        raise SLMParseError("Cloud API integration is not yet implemented.")
        
    elif app_settings.slm_provider == 'Download Llama-cpp':
        # Stub for local python process inference
        raise SLMParseError("Llama-cpp local python inference is not yet implemented.")
        
    return {}
