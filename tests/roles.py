"""Test helper: a person's role in the campaign (campaign_members), since roles are per campaign."""

from sqlalchemy import select

from app import access
from app.models import Campaign, CampaignMember, Role, User


def set_role(db, email: str, role: str = "dm", name: str = "Dee", campaign: Campaign | None = None) -> User:
    """Give `email` this role in the campaign (the first one, made as "main" if there's none yet)."""
    u = db.scalar(select(User).where(User.email == email)) or User(email=email, name=name)
    db.add(u)
    campaign = campaign or db.scalar(select(Campaign).order_by(Campaign.id))
    if campaign is None:
        campaign = Campaign(slug="main", name="Main")
        db.add(campaign)
    db.flush()
    m = db.scalar(select(CampaignMember).where(CampaignMember.user_id == u.id, CampaignMember.campaign_id == campaign.id,
                                               CampaignMember.left_on.is_(None)))
    if m is None:
        db.add(CampaignMember(user_id=u.id, campaign_id=campaign.id, role=Role(role)))
    else:
        m.role = Role(role)
    db.flush()
    access.invalidate()
    return u
