import re
import sys
import json
import math
import os

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

# Helper to round to nearest 100
def round_100(value):
    return int(round(value / 100.0)) * 100

def extract_coverage(text):
    result = {}
    lines = text.splitlines()
    # Patterns to match a dollar amount (with or without commas)
    dollar_pattern = re.compile(r'\$([\d,]+)')

    # Initialize flags for each coverage type
    found_bi = found_pd = found_um = found_comp = found_coll = False

    for line in lines:
        l = line.lower()
        # Bodily Injury
        if not found_bi and 'bodily injury' in l:
            m = dollar_pattern.findall(line)
            if len(m) >= 2:
                result['BodilyInjury'] = {
                    'PerPerson': round_100(int(m[0].replace(',', ''))),
                    'PerAccident': round_100(int(m[1].replace(',', '')))
                }
                found_bi = True
        # Property Damage
        elif not found_pd and 'property damage' in l:
            m = dollar_pattern.findall(line)
            if m:
                result['PropertyDamage'] = {
                    'PerAccident': round_100(int(m[0].replace(',', '')))
                }
                found_pd = True
        # Uninsured Motorist
        elif not found_um and 'uninsured' in l and 'motorist' in l:
            m = dollar_pattern.findall(line)
            if len(m) >= 2:
                result['UninsuredMotorist'] = {
                    'PerPerson': round_100(int(m[0].replace(',', ''))),
                    'PerAccident': round_100(int(m[1].replace(',', '')))
                }
                found_um = True
        # Comprehensive Deductible
        elif not found_comp and 'comprehensive' in l:
            m = dollar_pattern.findall(line)
            if m:
                result['ComprehensiveDeductible'] = round_100(int(m[0].replace(',', '')))
                found_comp = True
        # Collision Deductible
        elif not found_coll and 'collision' in l:
            m = dollar_pattern.findall(line)
            if m:
                result['CollisionDeductible'] = round_100(int(m[0].replace(',', '')))
                found_coll = True
        # Personal Injury Protection
        elif 'personal injury protection' in l:
            m = dollar_pattern.findall(line)
            if m:
                result['PersonalInjuryProtection'] = round_100(int(m[0].replace(',', '')))
        # Medical Payments (separate from PIP)
        elif 'medical payments' in l or 'medical payment' in l or 'medpay' in l:
            m = dollar_pattern.findall(line)
            if m:
                result['MedicalPayments'] = round_100(int(m[0].replace(',', '')))
        # Rental Reimbursement
        elif 'rental reimbursement' in l:
            rent_match = re.search(r'\$([\d,]+) each day/maximum (\d+) days', line, re.IGNORECASE)
            if rent_match:
                result['RentalReimbursement'] = {
                    'PerDay': int(rent_match.group(1).replace(',', '')),
                    'MaxDays': int(rent_match.group(2))
                }
    drivers = []
    vehicles = []
    # Extract drivers
    driver_section = False
    for idx, line in enumerate(lines):
        l = line.lower().strip()
        # Detect start of drivers section
        if 'drivers and household residents' in l:
            driver_section = True
            continue
        if driver_section:
            # End of drivers section (next section or empty line)
            if l == '' or 'additional information' in l or 'form' in l:
                driver_section = False
                continue
            # Extract driver name (First name = first word, Last name = rest)
            name_match = re.match(r'([A-Z][a-zA-Z]*)\s+([A-Z][a-zA-Z\s\-]+)', line.strip())
            if name_match:
                drivers.append({
                    'FirstName': name_match.group(1),
                    'LastName': name_match.group(2).strip()
                })
    # Extract vehicles
    vehicle = {}
    for idx, line in enumerate(lines):
        l = line.lower().strip()
        # Detect start of vehicle section
        if re.match(r'\d{4} [a-zA-Z]+ [a-zA-Z0-9 ]+', line.strip()):
            # Save previous vehicle if exists
            if vehicle:
                vehicles.append(vehicle)
            vehicle = {}
            # Year, Make, Model
            vm = re.match(r'(\d{4}) ([a-zA-Z]+) ([a-zA-Z0-9 ]+)', line.strip())
            if vm:
                vehicle['Year'] = vm.group(1)
                vehicle['Make'] = vm.group(2)
                vehicle['Model'] = vm.group(3).strip()
        # VIN
        vin_match = re.match(r'vin: ([a-zA-Z0-9]+)', l)
        if vin_match:
            vehicle['VIN'] = vin_match.group(1)
        # Garaging ZIP Code
        zip_match = re.match(r'garaging zip code: (\d{5})', l)
        if zip_match:
            vehicle['GaragingZIP'] = zip_match.group(1)
        # Primary use
        use_match = re.match(r'primary use of the vehicle: (.+)', l)
        if use_match:
            vehicle['PrimaryUse'] = use_match.group(1).strip()
        # Annual miles
        miles_match = re.match(r'annual miles: ([\d,\- ]+)', l)
        if miles_match:
            vehicle['AnnualMiles'] = miles_match.group(1).strip()
        # Length of vehicle ownership
        own_match = re.match(r'length of vehicle ownership when policy started or vehicle added: (.+)', l)
        if own_match:
            vehicle['OwnershipLength'] = own_match.group(1).strip()
    # Save last vehicle
    if vehicle:
        vehicles.append(vehicle)
    if drivers:
        result['Drivers'] = drivers
    if vehicles:
        result['Vehicles'] = vehicles
    return result

def extract_text_from_pdf(pdf_path):
    if not pdfplumber:
        raise ImportError("pdfplumber is required for PDF extraction. Please install it with 'pip install pdfplumber'.")
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_coverage.py <input_file.txt|input_file.pdf>")
        sys.exit(1)
    input_path = sys.argv[1]
    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".pdf":
        text = extract_text_from_pdf(input_path)
        print("--- Extracted PDF Text Start ---\n")
        print(text)
        print("\n--- Extracted PDF Text End ---\n")
    else:
        with open(input_path, 'r', encoding='utf-8') as f:
            text = f.read()
    coverage = extract_coverage(text)
    print(json.dumps(coverage, indent=2))
    # Write output to a .txt file
    output_file = os.path.splitext(input_path)[0] + "_output.txt"
    with open(output_file, 'w', encoding='utf-8') as out_f:
        out_f.write(json.dumps(coverage, indent=2))
    print(f"\nData written to {output_file}")
