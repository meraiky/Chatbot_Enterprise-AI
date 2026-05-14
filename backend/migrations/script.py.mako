"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports}

def upgrade():
    ${upgrades}

def downgrade():
    ${downgrades}
