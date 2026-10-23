import { useEffect, useState } from 'react';
import { Header } from './components/Header';
import { ProfileForm } from './components/ProfileForm';
import { ResearchProgress } from './components/ResearchProgress';
import { OpportunityList } from './components/OpportunityList';
import { SOPViewer } from './components/SOPViewer';
import { getOpportunities, getSession, getSop } from './api';
import type { SessionRecord, SOPDraft, VerifiedOpportunity } from './types';

export function App() {
  const [activeTab, setActiveTab] = useState<'profile' | 'research' | 'opportunities' | 'sop'>('profile');
  const [sessionId, setSessionId] = useState<string | null>(() => {
    return localStorage.getItem('scholarswarm_session_id') || null;
  });

  const [session, setSession] = useState<SessionRecord | null>(null);
  const [opportunities, setOpportunities] = useState<VerifiedOpportunity[]>([]);
  const [sop, setSop] = useState<SOPDraft | null>(null);
  const [loadingSop, setLoadingSop] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  // Sync session ID to localStorage
  const handleSetSessionId = (id: string | null) => {
    setSessionId(id);
    if (id) {
      localStorage.setItem('scholarswarm_session_id', id);
    } else {
      localStorage.removeItem('scholarswarm_session_id');
      setSession(null);
      setOpportunities([]);
      setSop(null);
      setActiveTab('profile');
    }
  };

  // Restore session from localStorage on initial mount
  useEffect(() => {
    if (sessionId) {
      loadSessionData(sessionId);
    }
  }, [sessionId]);

  const loadSessionData = async (sid: string) => {
    try {
      setGlobalError(null);
      const sess = await getSession(sid);
      setSession(sess);

      // Attempt to load opportunities
      try {
        const opps = await getOpportunities(sid);
        setOpportunities(opps);
      } catch {
        // May not have run research yet
      }

      // Attempt to load SOP
      try {
        setLoadingSop(true);
        const s = await getSop(sid);
        setSop(s);
      } catch {
        // SOP may not exist yet
      } finally {
        setLoadingSop(false);
      }
    } catch {
      // Stale or non-existent session
      handleSetSessionId(null);
    }
  };

  const handleSessionCreated = (newSession: SessionRecord) => {
    setSession(newSession);
    handleSetSessionId(newSession.session_id);
    setActiveTab('research');
  };

  const handleResearchFinished = async () => {
    if (!sessionId) return;
    try {
      const opps = await getOpportunities(sessionId);
      setOpportunities(opps);
    } catch (err: any) {
      setGlobalError('Failed to fetch evaluated opportunities: ' + (err?.message || String(err)));
    }

    try {
      setLoadingSop(true);
      const s = await getSop(sessionId);
      setSop(s);
    } catch {
      // SOP might not be generated if no candidates
    } finally {
      setLoadingSop(false);
    }

    setActiveTab('opportunities');
  };

  const handleSelectForSop = (_opp: VerifiedOpportunity) => {
    setActiveTab('sop');
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        sessionId={sessionId}
        onResetSession={() => handleSetSessionId(null)}
        hasOpportunities={opportunities.length > 0}
        hasSop={sop !== null}
      />

      <main style={{ flex: 1, paddingBottom: '60px' }}>
        {session?.student_profile && (
          <div style={{
            maxWidth: '1180px',
            margin: '16px auto 0',
            padding: '8px 18px',
            borderRadius: '8px',
            background: 'rgba(255, 255, 255, 0.03)',
            border: '1px solid var(--border-dim)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '8px',
            fontSize: '0.8125rem',
            color: '#94a3b8'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
              <span>
                Active Applicant: <strong style={{ color: '#ffffff' }}>{session.student_profile.name || 'Candidate'}</strong> ({session.student_profile.field_of_study} • {String(session.student_profile.target_degree).toUpperCase()})
              </span>
              {session.student_profile.cgpa !== null && session.student_profile.cgpa !== undefined && (
                <span>
                  {session.student_profile.cgpa_scale === 100.0 ? 'Grade (Percentage): ' : 'CGPA: '}
                  <strong style={{ color: '#ffffff' }}>{session.student_profile.cgpa}</strong>
                  {session.student_profile.cgpa_scale === 100.0
                    ? '%'
                    : session.student_profile.cgpa_scale
                    ? ` / ${session.student_profile.cgpa_scale}`
                    : ' (Scale: Unknown)'}
                </span>
              )}
              {session.student_profile.preferred_countries && session.student_profile.preferred_countries.length > 0 && (
                <span>
                  Target Destination: <strong style={{ color: '#ffffff' }}>{session.student_profile.preferred_countries.join(', ')}</strong>
                </span>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <button
                type="button"
                onClick={() => setActiveTab('profile')}
                className="btn btn-secondary"
                style={{ fontSize: '0.725rem', padding: '3px 10px' }}
                title="Edit current profile or verify grades"
              >
                Review Profile
              </button>
              <button
                type="button"
                onClick={() => handleSetSessionId(null)}
                className="btn btn-secondary"
                style={{ fontSize: '0.725rem', padding: '3px 10px', color: '#fb7185' }}
                title="Clear current session and start a fresh search"
              >
                New Session
              </button>
            </div>
          </div>
        )}

        {globalError && (
          <div style={{
            maxWidth: '1080px',
            margin: '20px auto 0',
            padding: '12px 20px',
            borderRadius: '10px',
            background: 'rgba(244, 63, 94, 0.12)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            color: '#fb7185',
            fontSize: '0.875rem'
          }}>
            {globalError}
          </div>
        )}

        {activeTab === 'profile' && (
          <ProfileForm
            onSessionCreated={handleSessionCreated}
            onResetSession={() => handleSetSessionId(null)}
          />
        )}

        {activeTab === 'research' && sessionId && (
          <ResearchProgress
            sessionId={sessionId}
            onResearchFinished={handleResearchFinished}
          />
        )}

        {activeTab === 'opportunities' && (
          <OpportunityList
            opportunities={opportunities}
            preferredCountries={session?.student_profile?.preferred_countries || []}
            onSelectForSop={handleSelectForSop}
          />
        )}

        {activeTab === 'sop' && (
          <SOPViewer
            sop={sop}
            loading={loadingSop}
          />
        )}
      </main>

      <footer style={{
        borderTop: '1px solid var(--border-dim)',
        padding: '24px 16px',
        textAlign: 'center',
        fontSize: '0.75rem',
        color: '#64748b'
      }}>
        <div style={{ maxWidth: '1080px', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <span>ScholarSwarm AI • Multi-Agent Autonomous Scholarship Research & Verification</span>
          <span>Grounding Tier T4 • Primary Source Provenance Policy Enforced</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
