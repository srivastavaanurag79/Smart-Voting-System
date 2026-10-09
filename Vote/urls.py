from django.urls import path, re_path

from . import views

app_name = "Vote"

urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("vote/", views.vote, name="vote"),
    path("results/", views.results, name="results"),
    path("tally/", views.run_tally, name="tally"),
    path("home/", views.home, name="home"),
    path("home_hindi/", views.home_hindi, name="home_hindi"),
    path("about/", views.about, name="about"),
    path("voted/", views.voted, name="voted"),
    path("invalid/", views.invalid, name="invalid"),
    path("casted/", views.casted, name="casted"),
    path("bulletin/", views.bulletin, name="bulletin"),
    path("verify/", views.verify_ballot, name="verify_ballot"),
    path("aadhaar/", views.aadhaar_verify, name="aadhaar_verify"),
    path("face_index/", views.face_index, name="face_index"),
    path("face_login/", views.face_login, name="face_login"),
    path("enroll/", views.enroll_face, name="enroll_face"),
    path("trainer/", views.trainer, name="trainer"),
    # Legacy paths kept so old links/bookmarks keep working.
    re_path(r"^detect/?$", views.detect, name="detect"),
    re_path(r"^create_dataset/?$", views.create_dataset, name="create_dataset"),
]
