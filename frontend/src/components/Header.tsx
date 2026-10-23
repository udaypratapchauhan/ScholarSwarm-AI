import React, { useEffect, useState } from 'react';
import { 
  Bot, 
  CheckCircle2, 
  Layers, 
  FileText, 
  Sparkles, 
  Copy, 
  Check, 
  PlusCircle 
} from 'lucide-react';
import { checkHealth } from '../api';
import type { HealthResponse } from '../types';

interface HeaderProps {
  activeTab: 'profile' | 'research' | 'opportunities' | 'sop';
  setActiveTab: (tab: 'profile' | 'research' | 'opportunities' | 'sop') => void;
  sessionId: string | null;
  onResetSession: () => void;
  hasOpportunities: boolean;
  hasSop: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  sessionId,
  onResetSession,
  hasOpportunities,
  hasSop,
}) => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let mounted = true;
    const fetchStatus = async () => {
      try {
        const h = await checkHealth();
        if (mounted) setHealth(h);
      } catch {
        if (mounted) setHealth({ status: 'unhealthy', database: 'disconnected', version: '0.1.0', timestamp: '' });
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const handleCopySession = () => {
    if (!sessionId) return;
    navigator.clipboard.writeText(sessionId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <header className="header-nav">
      <div style={{ maxWidth: '1280px', margin: '0 auto', padding: '14px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
          
          {/* Logo & Platform Info */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '42px',
              height: '42px',
              borderRadius: '12px',
              background: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(99, 102, 241, 0.4)'
            }}>
              <Bot size={24} color="#ffffff" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '1.25rem', fontWeight: '800', letterSpacing: '-0.02em', color: '#ffffff' }}>
                  ScholarSwarm<span style={{ color: '#06b6d4' }}>.AI</span>
                </span>
                <span style={{
                  fontSize: '0.675rem',
                  fontWeight: '700',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: 'rgba(99, 102, 241, 0.18)',
                  color: '#818cf8',
                  border: '1px solid rgba(99, 102, 241, 0.35)',
                  fontFamily: 'var(--font-mono)'
                }}>
                  SWARM v0.1
                </span>
              </div>
              <p style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                Multi-Agent Scholarship Discovery & Official Evidence Verification
              </p>
            </div>
          </div>

          {/* System Diagnostics & Session Chip */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            {/* Health pill */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.75rem',
              padding: '6px 12px',
              borderRadius: '20px',
              background: health?.status === 'healthy' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
              border: `1px solid ${health?.status === 'healthy' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(244, 63, 94, 0.3)'}`,
              color: health?.status === 'healthy' ? '#34d399' : '#fb7185'
            }}>
              <span style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: health?.status === 'healthy' ? '#10b981' : '#f43f5e',
                boxShadow: health?.status === 'healthy' ? '0 0 8px #10b981' : 'none'
              }} />
              <span>{health?.status === 'healthy' ? 'SQLite Connected' : 'Backend Disconnected'}</span>
            </div>

            {/* Active Session chip */}
            {sessionId && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '4px 6px 4px 12px',
                borderRadius: '20px',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-mid)',
                fontSize: '0.75rem',
                fontFamily: 'var(--font-mono)'
              }}>
                <span style={{ color: '#94a3b8' }}>Session:</span>
                <span style={{ color: '#f8fafc', fontWeight: '600' }}>{sessionId.slice(0, 16)}...</span>
                <button
                  onClick={handleCopySession}
                  title="Copy Session ID"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: copied ? '#34d399' : '#94a3b8',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    padding: '4px'
                  }}
                >
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                </button>
                <button
                  onClick={onResetSession}
                  title="Start New Session"
                  style={{
                    background: 'rgba(244, 63, 94, 0.15)',
                    border: '1px solid rgba(244, 63, 94, 0.3)',
                    color: '#fb7185',
                    borderRadius: '50%',
                    width: '22px',
                    height: '22px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer'
                  }}
                >
                  <PlusCircle size={14} />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Workflow Navigation Tabs */}
        <div style={{ display: 'flex', gap: '4px', marginTop: '16px', borderBottom: '1px solid var(--border-dim)', overflowX: 'auto' }}>
          <button
            className={`tab-btn ${activeTab === 'profile' ? 'active' : ''}`}
            onClick={() => setActiveTab('profile')}
            id="tab-profile"
          >
            <FileText size={16} />
            1. Student Profile & Upload
          </button>

          <button
            className={`tab-btn ${activeTab === 'research' ? 'active' : ''}`}
            onClick={() => setActiveTab('research')}
            disabled={!sessionId}
            id="tab-research"
            style={{ opacity: sessionId ? 1 : 0.4, cursor: sessionId ? 'pointer' : 'not-allowed' }}
          >
            <Layers size={16} />
            2. Multi-Agent Pipeline
          </button>

          <button
            className={`tab-btn ${activeTab === 'opportunities' ? 'active' : ''}`}
            onClick={() => setActiveTab('opportunities')}
            disabled={!hasOpportunities}
            id="tab-opportunities"
            style={{ opacity: hasOpportunities ? 1 : 0.4, cursor: hasOpportunities ? 'pointer' : 'not-allowed' }}
          >
            <CheckCircle2 size={16} />
            3. Verified Opportunities
          </button>

          <button
            className={`tab-btn ${activeTab === 'sop' ? 'active' : ''}`}
            onClick={() => setActiveTab('sop')}
            disabled={!hasSop}
            id="tab-sop"
            style={{ opacity: hasSop ? 1 : 0.4, cursor: hasSop ? 'pointer' : 'not-allowed' }}
          >
            <Sparkles size={16} />
            4. SOP & Strategy Draft
          </button>
        </div>

      </div>
    </header>
  );
};
