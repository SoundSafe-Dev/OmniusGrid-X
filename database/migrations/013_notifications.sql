-- Notifications & delivery center: subscription rules + delivery log

CREATE TABLE IF NOT EXISTS notification_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    channel VARCHAR(20) NOT NULL,             -- webhook | slack | email
    target VARCHAR(1024) NOT NULL,            -- URL or email address
    min_severity VARCHAR(20) DEFAULT 'warning', -- info|warning|error|critical
    domain VARCHAR(100),                      -- optional filter
    asset_id UUID,                            -- optional filter
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_subs_org ON notification_subscriptions(organization_id);
CREATE INDEX IF NOT EXISTS idx_notif_subs_enabled ON notification_subscriptions(enabled);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID,
    subscription_id UUID,
    channel VARCHAR(20),
    severity VARCHAR(20),
    title VARCHAR(512),
    message TEXT,
    delivered BOOLEAN DEFAULT false,
    detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_deliveries_org ON notification_deliveries(organization_id);
CREATE INDEX IF NOT EXISTS idx_notif_deliveries_created ON notification_deliveries(created_at);
