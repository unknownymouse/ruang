from django.urls import path

from . import views

app_name = "automation"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("brand-brain/", views.update_brand_brain, name="update_brand_brain"),
    path("prompts/new-version/", views.create_prompt_version, name="create_prompt_version"),
    path("campaigns/create/", views.create_campaign, name="create_campaign"),
    path("campaigns/<uuid:campaign_id>/", views.campaign_detail, name="campaign_detail"),
    path("campaigns/<uuid:campaign_id>/regenerate/", views.regenerate_campaign, name="regenerate_campaign"),
    path("campaigns/<uuid:campaign_id>/approve/", views.approve_campaign, name="approve_campaign"),
    path("drafts/<uuid:draft_id>/", views.update_draft, name="update_draft"),
    path("drafts/<uuid:draft_id>/media/<str:kind>/", views.queue_media, name="queue_media"),
]
