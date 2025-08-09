from app import create_app, db
from models import GlobalKnowledge

# Create a Flask app context to interact with the database
app = create_app()
with app.app_context():
    # Define the new global fact
    home_location_fact = GlobalKnowledge(
        query_text="home_location",
        response_content="Smiths Grove, KY 42171"
    )
    
    # Check if the fact already exists to avoid duplicates
    existing_fact = GlobalKnowledge.query.filter_by(query_text="home_location").first()
    if not existing_fact:
        db.session.add(home_location_fact)
        db.session.commit()
        print("Successfully added home location to global facts.")
    else:
        print("Home location fact already exists.")