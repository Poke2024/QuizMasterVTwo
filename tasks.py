import os
import csv
import io
import json
import requests
from datetime import datetime, date, timedelta
from celery import Celery
from celery.schedules import crontab
from flask_mail import Mail, Message
from flask import render_template, current_app

import config

# Create Celery instance
celery_app = Celery(
    'quiz_master',
    broker=config.REDIS_URL,
    backend=config.REDIS_URL
)

# Configure Celery
celery_app.conf.update(
    broker_url=config.CELERY_BROKER_URL,
    result_backend=config.CELERY_RESULT_BACKEND,
    accept_content=config.CELERY_ACCEPT_CONTENT,
    task_serializer=config.CELERY_TASK_SERIALIZER,
    result_serializer=config.CELERY_RESULT_SERIALIZER,
    timezone=config.CELERY_TIMEZONE
)

# Configure periodic tasks
celery_app.conf.beat_schedule = {
    # Daily reminder at 6 PM
    'send-daily-reminders': {
        'task': 'tasks.send_daily_reminders',
        'schedule': crontab(hour=18, minute=0)
    },
    # Monthly activity report on the 1st of each month
    'send-monthly-reports': {
        'task': 'tasks.send_monthly_reports',
        'schedule': crontab(day_of_month=1, hour=8, minute=0)
    }
}

# Helper functions to create Flask app
def create_app():
    from app import create_app as create_flask_app
    return create_flask_app()

def get_db():
    from app import db
    return db

def get_mail():
    from app import mail
    return mail

# Task to export users to CSV
@celery_app.task(bind=True)
def export_users_csv(self):
    try:
        app = create_app()
        
        with app.app_context():
            from models import User, Score
            
            # Set up StringIO object for CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'User ID', 'Username', 'Full Name', 'Qualification', 
                'Date of Birth', 'Registration Date', 'Quizzes Taken',
                'Average Score', 'Last Login'
            ])
            
            # Get all users
            users = User.query.filter_by(role='user').all()
            
            # Write data
            for user in users:
                # Calculate stats
                quizzes_taken = Score.query.filter_by(user_id=user.id).count()
                
                # Calculate average score
                from sqlalchemy import func
                avg_score = 0
                if quizzes_taken > 0:
                    avg_score_query = Score.query.with_entities(
                        func.avg(Score.score / Score.total_questions * 100)
                    ).filter_by(user_id=user.id).scalar()
                    avg_score = float(avg_score_query) if avg_score_query else 0
                
                writer.writerow([
                    user.id,
                    user.username,
                    user.full_name,
                    user.qualification or '',
                    user.dob.strftime('%Y-%m-%d') if user.dob else '',
                    user.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    quizzes_taken,
                    f"{avg_score:.2f}%",
                    user.last_login.strftime('%Y-%m-%d %H:%M:%S') if user.last_login else ''
                ])
            
            # Set file content
            output.seek(0)
            csv_content = output.getvalue()
            
            # Save to temporary file
            filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = os.path.join('/tmp', filename)
            
            with open(filepath, 'w') as f:
                f.write(csv_content)
                
            return {
                'filename': filename,
                'filepath': filepath,
                'download_url': f"/api/admin/export/download/{filename}"
            }
    
    except Exception as e:
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise e

# Task to export quizzes to CSV
@celery_app.task(bind=True)
def export_quizzes_csv(self):
    try:
        app = create_app()
        
        with app.app_context():
            from models import Quiz, Chapter, Subject, Score, User
            
            # Set up StringIO object for CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Quiz ID', 'Title', 'Subject', 'Chapter', 
                'Date', 'Duration (minutes)', 'Is Active', 
                'Total Attempts', 'Average Score', 'Highest Score'
            ])
            
            # Get all quizzes
            quizzes = Quiz.query.all()
            
            # Write data
            for quiz in quizzes:
                chapter = Chapter.query.get(quiz.chapter_id)
                subject = Subject.query.get(chapter.subject_id)
                
                # Calculate stats
                total_attempts = Score.query.filter_by(quiz_id=quiz.id).count()
                
                # Calculate average score
                from sqlalchemy import func
                avg_score = 0
                highest_score = 0
                
                if total_attempts > 0:
                    avg_score_query = Score.query.with_entities(
                        func.avg(Score.score / Score.total_questions * 100)
                    ).filter_by(quiz_id=quiz.id).scalar()
                    avg_score = float(avg_score_query) if avg_score_query else 0
                    
                    highest_score_query = Score.query.with_entities(
                        func.max(Score.score / Score.total_questions * 100)
                    ).filter_by(quiz_id=quiz.id).scalar()
                    highest_score = float(highest_score_query) if highest_score_query else 0
                
                writer.writerow([
                    quiz.id,
                    quiz.title,
                    subject.name,
                    chapter.name,
                    quiz.date_of_quiz.strftime('%Y-%m-%d'),
                    quiz.time_duration,
                    'Yes' if quiz.is_active else 'No',
                    total_attempts,
                    f"{avg_score:.2f}%",
                    f"{highest_score:.2f}%"
                ])
            
            # Set file content
            output.seek(0)
            csv_content = output.getvalue()
            
            # Save to temporary file
            filename = f"quizzes_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = os.path.join('/tmp', filename)
            
            with open(filepath, 'w') as f:
                f.write(csv_content)
                
            return {
                'filename': filename,
                'filepath': filepath,
                'download_url': f"/api/admin/export/download/{filename}"
            }
    
    except Exception as e:
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise e

# Task to export user's quiz attempts to CSV
@celery_app.task(bind=True)
def export_user_attempts_csv(self, user_id):
    try:
        app = create_app()
        
        with app.app_context():
            from models import User, Score, Quiz, Chapter, Subject
            
            # Get user
            user = User.query.get(user_id)
            
            if not user:
                raise ValueError(f"User with ID {user_id} not found")
            
            # Set up StringIO object for CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Quiz ID', 'Quiz Title', 'Subject', 'Chapter', 
                'Date Attempted', 'Time Taken (seconds)', 'Score', 
                'Total Questions', 'Percentage', 'Pass/Fail'
            ])
            
            # Get all attempts
            attempts = Score.query.filter_by(user_id=user_id).all()
            
            # Write data
            for attempt in attempts:
                quiz = Quiz.query.get(attempt.quiz_id)
                chapter = Chapter.query.get(quiz.chapter_id)
                subject = Subject.query.get(chapter.subject_id)
                
                percentage = (attempt.score / attempt.total_questions * 100) if attempt.total_questions > 0 else 0
                
                writer.writerow([
                    quiz.id,
                    quiz.title,
                    subject.name,
                    chapter.name,
                    attempt.attempt_date.strftime('%Y-%m-%d %H:%M:%S'),
                    attempt.time_taken,
                    attempt.score,
                    attempt.total_questions,
                    f"{percentage:.2f}%",
                    'Pass' if percentage >= 60 else 'Fail'
                ])
            
            # Set file content
            output.seek(0)
            csv_content = output.getvalue()
            
            # Save to temporary file
            filename = f"user_{user_id}_attempts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = os.path.join('/tmp', filename)
            
            with open(filepath, 'w') as f:
                f.write(csv_content)
                
            return {
                'filename': filename,
                'filepath': filepath,
                'download_url': f"/api/user/export/download/{filename}"
            }
    
    except Exception as e:
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise e

# Function to send Google Chat webhook message
def send_gchat_webhook(webhook_url, message_text, title=None, sections=None):
    """
    Send a message to Google Chat via webhook
    
    Args:
        webhook_url (str): Google Chat webhook URL
        message_text (str): Main message text
        title (str, optional): Card title
        sections (list, optional): List of section dicts
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not webhook_url:
        return False
        
    # Prepare the message payload
    payload = {"text": message_text}
    
    # If title or sections provided, create a card instead
    if title or sections:
        card = {
            "header": {"title": title or "Quiz Master Notification"},
            "sections": sections or []
        }
        payload = {"cards": [card]}
    
    try:
        # Send the webhook request
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        return response.status_code == 200
    except Exception as e:
        current_app.logger.error(f"Google Chat webhook error: {str(e)}")
        return False

# Function to send SMS via Twilio
def send_sms_notification(phone_number, message):
    """
    Send SMS notification using Twilio
    
    Args:
        phone_number (str): Recipient phone number with country code
        message (str): SMS message text
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not all([
        current_app.config.get('TWILIO_ACCOUNT_SID'),
        current_app.config.get('TWILIO_AUTH_TOKEN'),
        current_app.config.get('TWILIO_PHONE_NUMBER')
    ]):
        current_app.logger.warning("Twilio credentials not configured")
        return False
    
    try:
        from twilio.rest import Client
        
        # Initialize Twilio client
        client = Client(
            current_app.config.get('TWILIO_ACCOUNT_SID'),
            current_app.config.get('TWILIO_AUTH_TOKEN')
        )
        
        # Send message
        message = client.messages.create(
            body=message,
            from_=current_app.config.get('TWILIO_PHONE_NUMBER'),
            to=phone_number
        )
        
        return True
    except Exception as e:
        current_app.logger.error(f"Twilio SMS error: {str(e)}")
        return False

# Task to send daily reminders
@celery_app.task
def send_daily_reminders():
    try:
        app = create_app()
        mail = Mail(app)
        db = get_db()
        
        with app.app_context():
            from models import User, Quiz, Score, UserPreference
            from sqlalchemy import func
            
            # Get active quizzes for today and future
            today = date.today()
            upcoming_quizzes = Quiz.query.filter(
                Quiz.is_active == True,
                Quiz.date_of_quiz >= today
            ).order_by(Quiz.date_of_quiz).limit(5).all()
            
            # Get users who haven't logged in recently
            recent_date = datetime.now() - timedelta(days=3)
            inactive_users = User.query.filter(
                User.role == 'user',
                (User.last_login == None) | (User.last_login < recent_date)
            ).all()
            
            reminders_sent = 0
            
            # Send reminders to each user
            for user in inactive_users:
                # Get user's quiz attempts
                from app import db
                user_quizzes = db.session.query(Score.quiz_id).filter_by(user_id=user.id).all()
                user_quiz_ids = [q.quiz_id for q in user_quizzes]
                
                # Filter quizzes the user hasn't attempted
                new_quizzes = [quiz for quiz in upcoming_quizzes if quiz.id not in user_quiz_ids]
                
                if not new_quizzes:
                    continue  # Skip if no new quizzes
                
                # Get user preferences (if available)
                user_pref = UserPreference.query.filter_by(user_id=user.id).first()
                
                # Default to email if no preferences set
                notification_type = 'email'
                reminder_time = 18  # 6 PM default
                
                if user_pref:
                    notification_type = user_pref.notification_type or 'email'
                    reminder_time = user_pref.reminder_time or 18
                
                # Check if it's the right time to send reminder
                current_hour = datetime.now().hour
                if current_hour != reminder_time:
                    continue
                
                # Format quiz information for notifications
                quiz_info = []
                for i, quiz in enumerate(new_quizzes, 1):
                    quiz_info.append(f"{i}. {quiz.title} ({quiz.date_of_quiz.strftime('%Y-%m-%d')})")
                
                quiz_list = "\n".join(quiz_info)
                
                # Send notification based on user preference
                if notification_type == 'email':
                    # Prepare email content
                    html = render_template(
                        'daily_reminder.html',
                        user=user,
                        quizzes=new_quizzes,
                        date=today
                    )
                    
                    # Send email
                    msg = Message(
                        subject="Quiz Master - Daily Reminder",
                        recipients=[user.username],  # Username is email
                        html=html,
                        sender=app.config.get('MAIL_DEFAULT_SENDER')
                    )
                    mail.send(msg)
                    reminders_sent += 1
                
                elif notification_type == 'gchat' and user_pref.webhook_url:
                    # Create Google Chat message
                    sections = [{
                        "header": "New Quizzes Available",
                        "widgets": [{"textParagraph": {"text": quiz_list}}]
                    }]
                    
                    # Add call to action button
                    sections.append({
                        "widgets": [{
                            "buttons": [{
                                "textButton": {
                                    "text": "Go to Quiz Master",
                                    "onClick": {"openLink": {"url": app.config.get('APP_URL', 'https://quizmaster.com')}}
                                }
                            }]
                        }]
                    })
                    
                    # Send webhook
                    success = send_gchat_webhook(
                        user_pref.webhook_url,
                        f"Hi {user.full_name}, you have {len(new_quizzes)} new quizzes available!",
                        "Quiz Master Daily Reminder",
                        sections
                    )
                    
                    if success:
                        reminders_sent += 1
                
                elif notification_type == 'sms' and user_pref.phone_number:
                    # Create SMS message
                    sms_text = f"Hi {user.full_name}, you have {len(new_quizzes)} new quizzes available on Quiz Master:\n\n{quiz_list}\n\nLogin to attempt them!"
                    
                    # Send SMS
                    success = send_sms_notification(user_pref.phone_number, sms_text)
                    
                    if success:
                        reminders_sent += 1
            
            return f"Daily reminders sent to {reminders_sent} users"
    
    except Exception as e:
        current_app.logger.error(f"Daily reminder error: {str(e)}")
        raise e

# Task to send monthly reports
@celery_app.task
def send_monthly_reports():
    try:
        app = create_app()
        mail = Mail(app)
        
        with app.app_context():
            from models import User, Score, Quiz, Chapter, Subject
            from sqlalchemy import func
            
            # Get previous month
            today = date.today()
            first_day = date(today.year, today.month, 1)
            if today.month == 1:
                last_month = date(today.year - 1, 12, 1)
            else:
                last_month = date(today.year, today.month - 1, 1)
            
            # Get all users
            users = User.query.filter_by(role='user').all()
            
            # Send reports to each user
            for user in users:
                # Get user's quiz attempts from last month
                attempts = Score.query.filter(
                    Score.user_id == user.id,
                    Score.attempt_date >= last_month,
                    Score.attempt_date < first_day
                ).all()
                
                if not attempts:
                    continue  # Skip users with no activity
                
                # Calculate stats
                total_attempts = len(attempts)
                total_score = sum(a.score for a in attempts)
                total_questions = sum(a.total_questions for a in attempts)
                avg_percentage = (total_score / total_questions * 100) if total_questions > 0 else 0
                
                # Get detailed attempt info
                attempt_details = []
                for attempt in attempts:
                    quiz = Quiz.query.get(attempt.quiz_id)
                    chapter = Chapter.query.get(quiz.chapter_id)
                    subject = Subject.query.get(chapter.subject_id)
                    
                    percentage = (attempt.score / attempt.total_questions * 100) if attempt.total_questions > 0 else 0
                    
                    attempt_details.append({
                        'quiz_title': quiz.title,
                        'subject': subject.name,
                        'chapter': chapter.name,
                        'score': attempt.score,
                        'total': attempt.total_questions,
                        'percentage': percentage,
                        'date': attempt.attempt_date.strftime('%Y-%m-%d %H:%M')
                    })
                
                # Get rankings
                user_rankings = {}
                for attempt in attempts:
                    # Get user's rank for this quiz
                    from app import db
                    rank = db.session.query(
                        func.count(Score.id) + 1
                    ).filter(
                        Score.quiz_id == attempt.quiz_id,
                        Score.score > attempt.score
                    ).scalar() or 1
                    
                    total_attempts_for_quiz = Score.query.filter_by(quiz_id=attempt.quiz_id).count()
                    
                    quiz = Quiz.query.get(attempt.quiz_id)
                    
                    user_rankings[quiz.title] = {
                        'rank': rank,
                        'total': total_attempts_for_quiz
                    }
                
                # Prepare email content
                html = render_template(
                    'monthly_report.html',
                    user=user,
                    month=last_month.strftime('%B %Y'),
                    total_attempts=total_attempts,
                    avg_percentage=avg_percentage,
                    attempts=attempt_details,
                    rankings=user_rankings
                )
                
                # Send email
                msg = Message(
                    subject=f"Quiz Master - Monthly Activity Report ({last_month.strftime('%B %Y')})",
                    recipients=[user.username],  # Username is email
                    html=html,
                    sender=app.config['MAIL_DEFAULT_SENDER']
                )
                mail.send(msg)
            
            return f"Monthly reports sent to {len(users)} users"
    
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Monthly report error: {str(e)}")
        raise e
