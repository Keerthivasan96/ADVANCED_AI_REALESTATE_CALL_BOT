# twilio_webhook_reliable.py - Simplified and more reliable

import time
import logging
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from app.property_rag import RealEstateRAG
import google.generativeai as genai

# Configure logging
logging.basicConfig(level=logging.INFO)

# Init Flask + Pre-load models
app = Flask(__name__)
rag = RealEstateRAG()

# Pre-warm Gemini
print("🚀 Pre-warming Gemini...")
model = genai.GenerativeModel("gemini-2.5-flash")
_ = model.generate_content("test").text
print("✅ Gemini ready")

# Simple session storage
sessions = {}

class ReliableVoiceAssistant:
    """Simplified, more reliable version for phone calls"""
    
    def __init__(self, call_id):
        self.call_id = call_id
        self.client_data = {
            'name': 'John Smith',
            'location': 'Downtown Dubai',
            'bedrooms': 2,
            'bought_price': 1_200_000,
            'current_price': 3_300_000,
            'purchase_year': 2020
        }
        self.exchange_count = 0
        self.confirmed = False
        self.rejected = False

    def get_quick_response(self, user_input):
        """Fast cached responses for common inputs"""
        
        profit = self.client_data['current_price'] - self.client_data['bought_price']
        roi = (profit / self.client_data['bought_price']) * 100
        
        # Positive responses
        if any(word in user_input for word in ["yes", "interested", "tell me", "go ahead", "sure", "okay"]):
            responses = [
                f"Excellent! Your property gained {profit:,} dirhams since {self.client_data['purchase_year']}. That's {roi:.0f} percent return. The timing is perfect to maximize this further.",
                "Great! With Dubai's market momentum, smart investors are repositioning now. Would you like to hear about strategic options that could double your returns?",
                "Perfect timing! Your villa's performance shows you make smart investment decisions. Let me share how successful investors are leveraging this market cycle."
            ]
            return responses[self.exchange_count % len(responses)]
        
        # Negative responses
        elif any(word in user_input for word in ["no", "not interested", "busy", "later", "don't want"]):
            responses = [
                "I understand you're busy. Just consider - your property doubled in value. What if it could double again through smart repositioning? Just 2 minutes of your time?",
                "No problem. But before I go - would you rather lock in your 2.1 million dirham profit now, or risk waiting through the summer slowdown? Quick question for you.",
                "I respect that. Market timing is personal. If your situation changes, our senior advisors are always available. Have a great day!"
            ]
            if self.exchange_count >= 2:
                return responses[2]  # Exit gracefully after 2 rejections
            return responses[self.exchange_count % 2]
        
        # Question responses  
        elif any(word in user_input for word in ["how", "what", "where", "when", "why"]):
            return "Great question! The strategy is simple - sell your villa at peak value, then acquire 2-3 apartments in high-growth areas. This multiplies your rental income and capital appreciation. Interested in the specifics?"
        
        # Default response
        return f"Based on your excellent {roi:.0f} percent return, you're clearly a smart investor. The question is - are you ready to potentially double these returns through strategic repositioning?"

    def generate_response(self, user_input):
        """Generate response with fallback to quick responses"""
        
        # Try quick response first
        quick_response = self.get_quick_response(user_input)
        if quick_response:
            return quick_response
        
        # Generate custom response for complex queries
        try:
            profit = self.client_data['current_price'] - self.client_data['bought_price']
            roi = (profit / self.client_data['bought_price']) * 100
            
            prompt = f'''You are Alexa from Baaz Landmark Real Estate Dubai.

Client: {self.client_data['name']} owns {self.client_data['bedrooms']}-bed villa in {self.client_data['location']}.
Investment: Bought {self.client_data['purchase_year']} for {self.client_data['bought_price']:,} AED, now worth {self.client_data['current_price']:,} AED.
Performance: {profit:,} AED profit ({roi:.0f}% return)

User said: "{user_input}"

Respond as a phone conversation:
- 1-2 sentences maximum
- Natural, conversational tone
- Focus on investment opportunity 
- End with engaging question
- Speak for phone clarity (say "Arab Emirates Dirham" not "AED")

Response:'''

            response = model.generate_content(prompt).text.strip()
            
            # Ensure appropriate length
            if len(response) > 200:
                sentences = response.split('.')
                response = '.'.join(sentences[:2]) + '.'
            
            return response
            
        except Exception as e:
            logging.error(f"Gemini error: {e}")
            return self.get_quick_response("default")

def clean_for_speech(text):
    """Simple text cleaning for phone speech"""
    replacements = {
        'AED': 'Arab Emirates Dirham',
        'ROI': 'return on investment',
        'AI': 'A.I.',
        '3.3M': '3.3 million',
        '1.2M': '1.2 million',
        '2.1M': '2.1 million',
        '%': ' percent',
        '&': ' and ',
        'vs': 'versus'
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text

@app.route("/voice", methods=["POST"])
def voice():
    """Entry point - start conversation"""
    call_sid = request.form.get("CallSid")
    
    # Create new session
    sessions[call_sid] = {
        'bot': ReliableVoiceAssistant(call_sid),
        'start_time': time.time()
    }
    
    bot = sessions[call_sid]['bot']
    
    resp = VoiceResponse()
    
    # Simple, effective greeting
    profit = bot.client_data['current_price'] - bot.client_data['bought_price']
    roi = (profit / bot.client_data['bought_price']) * 100
    
    greeting = (
        f"Hi {bot.client_data['name']}, this is Alexa from Baaz Landmark Real Estate. "
        f"Your {bot.client_data['location']} property gained {profit:,} Arab Emirates Dirhams since {bot.client_data['purchase_year']}. "
        f"That's {roi:.0f} percent return on investment! Are you interested in maximizing this further?"
    )

    # Simple gather with good timeout
    gather = Gather(input="speech", action="/process", timeout=5)
    gather.say(clean_for_speech(greeting), voice="alice")
    resp.append(gather)

    # Fallback
    resp.say("I didn't hear a response. Our team will call you back. Goodbye!", voice="alice")
    resp.hangup()
    
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    """Process user responses"""
    call_sid = request.form.get("CallSid")
    
    if call_sid not in sessions:
        resp = VoiceResponse()
        resp.say("Session expired. Please call back.", voice="alice")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")
    
    bot = sessions[call_sid]['bot']
    resp = VoiceResponse()

    try:
        user_input = request.form.get("SpeechResult", "").lower()
        logging.info(f"Call {call_sid}: User said '{user_input}'")

        # Handle empty input
        if not user_input.strip():
            if bot.exchange_count == 0:
                gather = Gather(input="speech", action="/process", timeout=5)
                gather.say("I didn't catch that. Are you interested in hearing about maximizing your property returns?", voice="alice")
                resp.append(gather)
                return Response(str(resp), mimetype="text/xml")
            else:
                resp.say("I'm having trouble hearing you. Our senior advisor will call you back within 24 hours. Thank you!", voice="alice")
                resp.hangup()
                del sessions[call_sid]
                return Response(str(resp), mimetype="text/xml")

        bot.exchange_count += 1

        # Check for strong exit signals
        if any(phrase in user_input for phrase in ["not interested", "don't call", "remove me", "stop calling"]):
            resp.say("I understand. You'll be removed from our calling list. Have a great day!", voice="alice")
            resp.hangup()
            del sessions[call_sid]
            return Response(str(resp), mimetype="text/xml")

        # Check for strong positive signals
        if any(phrase in user_input for phrase in ["very interested", "let's do it", "send information", "connect me"]):
            resp.say("Excellent! I'll send you detailed investment projections via WhatsApp and have our senior advisor contact you within 24 hours with specific opportunities. Thank you!", voice="alice")
            resp.hangup()
            del sessions[call_sid]
            return Response(str(resp), mimetype="text/xml")

        # Generate response
        reply = bot.generate_response(user_input)
        clean_reply = clean_for_speech(reply)
        
        # Limit conversation length
        if bot.exchange_count >= 4:
            # Wrap up after 4 exchanges
            final_message = "I can see you need time to consider this. Our senior advisor will send you detailed information and follow up personally. Thank you for your time!"
            resp.say(clean_for_speech(final_message), voice="alice")
            resp.hangup()
            del sessions[call_sid]
            return Response(str(resp), mimetype="text/xml")

        # Continue conversation
        resp.say(clean_reply, voice="alice")
        
        gather = Gather(input="speech", action="/process", timeout=5)
        gather.say("What do you think?", voice="alice")
        resp.append(gather)

        return Response(str(resp), mimetype="text/xml")

    except Exception as e:
        logging.error(f"Error processing call {call_sid}: {e}")
        
        resp.say("I'm experiencing a technical issue. Our senior advisor will call you back shortly. Thank you!", voice="alice")
        resp.hangup()
        
        if call_sid in sessions:
            del sessions[call_sid]
            
        return Response(str(resp), mimetype="text/xml")

@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return {"status": "healthy", "sessions": len(sessions)}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)