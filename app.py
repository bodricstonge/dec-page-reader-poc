from flask import Flask, request, jsonify, send_from_directory
import os
from werkzeug.utils import secure_filename
from extract_coverage import extract_coverage, extract_text_from_pdf
import openai

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'txt'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Helper to call OpenAI ChatGPT API
def call_chatgpt_extraction(text, prompt=None):
    if not OPENAI_API_KEY:
        raise RuntimeError('OPENAI_API_KEY environment variable not set.')
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    if prompt is None:
        prompt = (
            "You are an expert at reading auto insurance declaration pages. "
            "Extract the following fields from the text below, even if the format varies: "
            "- Bodily Injury (Per Person, Per Accident)\n"
            "- Property Damage (Per Accident)\n"
            "- Uninsured Motorist (Per Person, Per Accident)\n"
            "- Comprehensive Deductible\n"
            "- Collision Deductible\n"
            "- Personal Injury Protection (PIP)\n"
            "- Medical Payments (MedPay)\n"
            "- Rental Reimbursement (Per Day, Max Days)\n"
            "- Drivers (First Name, Last Name)\n"
            "- Vehicles (Year, Make, Model, VIN, Garaging ZIP, Primary Use, Annual Miles, Ownership Length)\n"
            "If both Personal Injury Protection and Medical Payments are present, extract both as separate fields. Return the result as JSON.\n\n"
            "Declaration Page Text:\n" + text
        )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=1500
    )
    # Extract JSON from response
    import json as pyjson
    import re as pyre
    content = response.choices[0].message.content
    print("ChatGPT raw response:", content)  # For debugging
    match = pyre.search(r'\{[\s\S]*\}', content)
    if match:
        return pyjson.loads(match.group(0))
    else:
        return {"error": "Could not extract JSON from ChatGPT response", "raw": content}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/extract', methods=['POST'])
def extract():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.pdf':
            text = extract_text_from_pdf(file_path)
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        # Use ChatGPT for extraction
        data = call_chatgpt_extraction(text)  # <-- You can pass a custom prompt as the second argument here
        os.remove(file_path)
        # Ensure keys are in the expected format for the frontend
        def normalize_key(key):
            mapping = {
                'bodilyinjury': 'BodilyInjury',
                'bodilyinjuryliability': 'BodilyInjury',
                'bodilyinjurycoverage': 'BodilyInjury',
                'bi': 'BodilyInjury',
                'propertydamage': 'PropertyDamage',
                'propertydamageliability': 'PropertyDamage',
                'propertydamagecoverage': 'PropertyDamage',
                'pd': 'PropertyDamage',
                'uninsuredmotorist': 'UninsuredMotorist',
                'uninsuredmotoristcoverage': 'UninsuredMotorist',
                'uninsuredmotoristbodilyinjury': 'UninsuredMotorist',
                'um': 'UninsuredMotorist',
                'comprehensivedeductible': 'ComprehensiveDeductible',
                'comprehensive': 'ComprehensiveDeductible',
                'collisiondeductible': 'CollisionDeductible',
                'collision': 'CollisionDeductible',
                'personalinjuryprotection': 'PersonalInjuryProtection',
                'pip': 'PersonalInjuryProtection',
                'medicalpayments': 'MedicalPayments',
                'medicalpayment': 'MedicalPayments',
                'medpay': 'MedicalPayments',
                'rentalreimbursement': 'RentalReimbursement',
                'rental': 'RentalReimbursement',
                'drivers': 'Drivers',
                'driver': 'Drivers',
                'vehicles': 'Vehicles',
                'vehicle': 'Vehicles',
            }
            k = key.replace('_', '').replace(' ', '').replace('-', '').lower()
            return mapping.get(k, key[:1].upper() + key[1:])
        def format_keys_and_round(d, parent_key=None):
            import math
            def round_100(val):
                try:
                    num = float(val)
                    if num < 100:
                        return int(num)
                    return int(round(num / 100.0)) * 100
                except Exception:
                    return val
            def flatten_single_value_dict(v):
                # If dict has a single key and that key is a common wrapper, flatten it
                if isinstance(v, dict) and len(v) == 1:
                    key = list(v.keys())[0].lower()
                    if key in ["value", "amount", "limit", "coverage", "deductible"]:
                        return flatten_single_value_dict(list(v.values())[0])
                return v
            if isinstance(d, dict):
                new_dict = {}
                for k, v in d.items():
                    key = normalize_key(str(k))
                    v = flatten_single_value_dict(v)
                    # If the value is a dict and has a single key, flatten it (for LLM outputs like {"amount": "$100,000"})
                    if isinstance(v, dict) and len(v) == 1:
                        v = flatten_single_value_dict(v)
                    # Pass key as parent_key for recursion
                    new_dict[key] = format_keys_and_round(v, parent_key=key)
                return new_dict
            elif isinstance(d, list):
                return [format_keys_and_round(i, parent_key=parent_key) for i in d]
            elif isinstance(d, str):
                s = d.strip()
                if s.startswith('$'):
                    s = s[1:]
                s = s.replace(',', '')
                # Do not round vehicle year
                if parent_key == 'Year':
                    return s
                if s.isdigit():
                    return round_100(s)
                return s
            elif isinstance(d, (int, float)):
                # Do not round vehicle year
                if parent_key == 'Year':
                    return d
                return round_100(d)
            else:
                return d
        data = format_keys_and_round(data)
        print('Formatted data for frontend:', data)  # Debug print
        return jsonify(data)
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    app.run(debug=True)
