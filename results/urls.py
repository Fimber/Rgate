from django.urls import path

from results import views

app_name = "results"

urlpatterns = [
    path("scores/", views.score_home, name="score_home"),
    path("scores/<int:assignment_id>/", views.score_entry, name="score_entry"),
    path("scores/<int:assignment_id>/save/", views.score_save, name="score_save"),
    path("scores/<int:assignment_id>/submit/", views.score_submit, name="score_submit"),
    path("scores/<int:assignment_id>/unlock/", views.score_unlock, name="score_unlock"),
    path("scores/<int:assignment_id>/excel/", views.score_excel, name="score_excel"),
    path("progress/", views.progress, name="progress"),
    path("review/<int:class_id>/", views.review, name="review"),
    path("publish/", views.publish, name="publish"),
    path("preview/<int:sheet_id>/", views.preview, name="preview"),
    path("broadsheet/<int:class_id>/", views.broadsheet, name="broadsheet"),
    path("transcripts/", views.transcripts, name="transcripts"),
    path("transcripts/<int:student_id>/", views.transcript_detail, name="transcript"),
]
