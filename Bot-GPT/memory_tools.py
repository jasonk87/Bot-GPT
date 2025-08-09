# memory_tools.py
from models import db, User, UserMemory, UserRelationship, UserPreferences

def _save_user_fact(user_id: int, fact_key: str, fact_value: str):
    """
    Saves or updates a key-value fact to a specific user's long-term memory.
    This is a private tool for the Memory Agent.
    """
    if not user_id or not fact_key or not fact_value:
        return "Error: user_id, fact_key, and fact_value are required."

    user = User.query.get(user_id)
    if not user:
        return f"Error: User with ID {user_id} not found."

    # Check if this fact already exists for the user
    existing_fact = UserMemory.query.filter_by(user_id=user_id, fact_key=fact_key).first()
    
    if existing_fact:
        # Update the existing fact
        existing_fact.fact_value = fact_value
        db.session.commit()
        return f"Fact updated for {user.username}: '{fact_key}' is now '{fact_value}'."
    else:
        # Add a new fact
        new_fact = UserMemory(user_id=user_id, fact_key=fact_key, fact_value=fact_value)
        db.session.add(new_fact)
        db.session.commit()
        return f"New fact saved for {user.username}: '{fact_key}' is '{fact_value}'."

def _save_user_relationship(user_one_username: str, user_two_username: str, relationship_description: str):
    """
    Saves a relationship between two users.
    This is a private tool for the Memory Agent.
    """
    user_one = User.query.filter_by(username=user_one_username).first()
    user_two = User.query.filter_by(username=user_two_username).first()

    if not user_one or not user_two:
        return "Error: One or both users not found."

    # Check if the relationship already exists to avoid duplicates
    existing_rel = UserRelationship.query.filter_by(
        user_one_id=user_one.id, 
        user_two_id=user_two.id, 
        relationship_description=relationship_description
    ).first()
    
    if existing_rel:
        return "Relationship already exists."

    new_relationship = UserRelationship(
        user_one_id=user_one.id,
        user_two_id=user_two.id,
        relationship_description=relationship_description
    )
    db.session.add(new_relationship)
    db.session.commit()
    return f"Successfully saved relationship: {user_one.username} -> {relationship_description} -> {user_two.username}"

def _save_user_preference(user_id: int, preference_key: str, preference_value: str):
    """
    Saves or updates a key-value preference for a user.
    This is a private tool for the Memory Agent.
    """
    user = User.query.get(user_id)
    if not user:
        return f"Error: User with ID {user_id} not found."

    existing_pref = UserPreferences.query.filter_by(user_id=user_id, preference_key=preference_key).first()

    if existing_pref:
        existing_pref.preference_value = preference_value
        db.session.commit()
        return f"Preference updated for {user.username}: '{preference_key}' is now '{preference_value}'."
    else:
        new_pref = UserPreferences(user_id=user_id, preference_key=preference_key, preference_value=preference_value)
        db.session.add(new_pref)
        db.session.commit()
        return f"New preference saved for {user.username}: '{preference_key}' is '{preference_value}'."