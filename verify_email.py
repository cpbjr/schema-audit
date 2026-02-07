import os
from jinja2 import Environment, FileSystemLoader

# Mock data classes to simulate the real app structure
class MockBusiness:
    def __init__(self, name):
        self.name = name

class MockAudit:
    def __init__(self, score):
        self.score = score

def verify_email_template():
    # Setup Jinja2 environment
    template_dir = os.path.join(os.getcwd(), 'templates')
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('email_template.html')

    # Mock Data
    business = MockBusiness("Joe's Pizza")
    audit = MockAudit(2)  # Low score example
    
    # Rendering Context
    # Matches the logic in reporter.py for colors/quality
    context = {
        'business_name': business.name,
        'audit_score': audit.score,
        'lead_quality': "Needs Attention",
        'score_color': "#ef4444",
        'score_bg_color': "#fef2f2",
        'missing_fields': ['PostalAddress', 'geoCoordinates', 'openingHours']
    }

    # Render
    output = template.render(**context)

    # Save to file
    output_path = "verified_email_sample.html"
    with open(output_path, "w") as f:
        f.write(output)
    
    print(f"Verification successful! Open {output_path} to see the result.")

if __name__ == "__main__":
    verify_email_template()
