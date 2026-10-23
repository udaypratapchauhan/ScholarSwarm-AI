import React, { useEffect, useState, useRef } from 'react';
import { 
  Bot, 
  Search, 
  ShieldCheck, 
  BarChart3, 
  FileEdit, 
  CheckCircle2, 
  Loader2, 
  AlertTriangle, 
  ArrowRight,
  RefreshCw,
  Terminal
} from 'lucide-react';
import { getEvents, startResearch } from '../api';
import type { AgentRole, PipelineEvent } from '../types';

interface ResearchProgressProps {
  sessionId: string;
  onResearchFinished: () => void;
}

interface AgentStage {
  role: AgentRole;
  title: string;
  description: string;
  icon: React.ReactNode;
}

const AGENT_STAGES: AgentStage[] = [
  {
    role: 'SPA',
    title: 'Student Profile Agent (SPA)',
    description: 'Extracts credentials, verified skills, and academic profile from documents.',
    icon: <Bot size={20} />,
  },
  {
    role: 'ORA',
    title: 'Opportunity Research Agent (ORA)',
    description: 'Executes targeted search queries to discover live candidate programs.',
    icon: <Search size={20} />,
  },
  {
    role: 'EEVA',
    title: 'Eligibility & Verification Agent (EEVA)',
    description: 'Fetches official web pages, extracts structured requirements, and classifies T1-T4 tiers.',
    icon: <ShieldCheck size={20} />,
  },
  {
    role: 'MRA',
    title: 'Matching & Ranking Agent (MRA)',
    description: 'Scores eligible candidates using multi-factor weights and enforces strict T4 Top-5 rules.',
    icon: <BarChart3 size={20} />,
  },
  {
    role: 'ASA',
    title: 'Application / SOP Assistant (ASA)',
    description: 'Generates evidence-grounded Statement of Purpose draft and actionable application checklist.',
    icon: <FileEdit size={20} />,
  },
];

export const ResearchProgress: React.FC<ResearchProgressProps> = ({
  sessionId,
  onResearchFinished,
}) => {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isCompleted, setIsCompleted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summaryData, setSummaryData] = useState<{ opportunityCount?: number; top5Count?: number } | null>(null);
  
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastEventIdRef = useRef<string | undefined>(undefined);
  const hasTriggeredRef = useRef(false);

  // Poll Events
  const pollNewEvents = async () => {
    try {
      const newEvents = await getEvents(sessionId, lastEventIdRef.current);
      if (newEvents && newEvents.length > 0) {
        setEvents((prev) => {
          const ids = new Set(prev.map((e) => e.event_id));
          const filtered = newEvents.filter((e) => !ids.has(e.event_id));
          return [...prev, ...filtered];
        });
        lastEventIdRef.current = newEvents[newEvents.length - 1].event_id;

        // Check for terminal event
        const completedEvt = newEvents.find((e) => e.event_type === 'pipeline_completed');
        if (completedEvt) {
          setIsCompleted(true);
          setIsRunning(false);
          if (completedEvt.payload) {
            setSummaryData({
              opportunityCount: completedEvt.payload.opportunity_count,
              top5Count: completedEvt.payload.top_5_count,
            });
          }
          if (pollingRef.current) clearInterval(pollingRef.current);
        }
      }
    } catch {
      // transient polling error; continue
    }
  };

  // Launch research pipeline
  const runResearch = async () => {
    setError(null);
    setIsRunning(true);
    setIsCompleted(false);

    // Initial event poll
    await pollNewEvents();

    // Start interval
    pollingRef.current = setInterval(pollNewEvents, 1200);

    try {
      const res = await startResearch(sessionId);
      setSummaryData({
        opportunityCount: res.opportunity_count,
        top5Count: res.top_5_count,
      });
      // Do final event poll
      await pollNewEvents();
      setIsCompleted(true);
      setIsRunning(false);
    } catch (err: any) {
      setError(err?.message || 'Research execution failed. Please verify backend status.');
      setIsRunning(false);
    } finally {
      if (pollingRef.current) clearInterval(pollingRef.current);
    }
  };

  useEffect(() => {
    if (!hasTriggeredRef.current) {
      hasTriggeredRef.current = true;
      runResearch();
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [sessionId]);

  // Stage state computation
  const getStageStatus = (role: AgentRole): 'completed' | 'active' | 'waiting' => {
    const hasRoleEvent = events.some((e) => e.agent === role);
    if (isCompleted) return 'completed';
    if (!isRunning && events.length === 0) return 'waiting';

    const order: AgentRole[] = ['SPA', 'ORA', 'EEVA', 'MRA', 'ASA'];
    const activeIndex = order.findIndex((r) => r === role);
    const lastActiveAgent = events.length > 0 ? events[events.length - 1].agent : 'SPA';
    const lastIndex = order.findIndex((r) => r === lastActiveAgent);

    if (hasRoleEvent && activeIndex <= lastIndex) {
      return activeIndex < lastIndex ? 'completed' : 'active';
    }
    return 'waiting';
  };

  return (
    <div style={{ maxWidth: '1080px', margin: '32px auto', padding: '0 16px' }}>
      
      {/* Header Banner */}
      <div style={{ textAlign: 'center', marginBottom: '32px' }}>
        <h2 style={{ fontSize: '1.75rem', fontWeight: '800', color: '#ffffff', letterSpacing: '-0.02em' }}>
          Multi-Agent Research Pipeline
        </h2>
        <p style={{ color: '#94a3b8', fontSize: '0.9375rem', marginTop: '6px' }}>
          Orchestrating autonomous agents across discovery, primary-source verification, deterministic ranking, and SOP synthesis.
        </p>
      </div>

      {error && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 20px',
          borderRadius: '12px',
          background: 'rgba(244, 63, 94, 0.12)',
          border: '1px solid rgba(244, 63, 94, 0.3)',
          color: '#fb7185',
          marginBottom: '28px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <AlertTriangle size={20} />
            <span>{error}</span>
          </div>
          <button
            onClick={runResearch}
            className="btn btn-secondary"
            style={{ padding: '6px 14px', fontSize: '0.8125rem' }}
          >
            <RefreshCw size={14} /> Retry Research
          </button>
        </div>
      )}

      {/* 5-Agent Flow Visualizer */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
        gap: '12px',
        marginBottom: '32px'
      }}>
        {AGENT_STAGES.map((stage) => {
          const status = getStageStatus(stage.role);
          return (
            <div
              key={stage.role}
              className="card-container"
              style={{
                padding: '20px 16px',
                background: status === 'active' 
                  ? 'rgba(99, 102, 241, 0.12)' 
                  : status === 'completed'
                  ? 'rgba(16, 185, 129, 0.08)'
                  : 'rgba(15, 21, 35, 0.6)',
                border: status === 'active'
                  ? '1px solid rgba(99, 102, 241, 0.5)'
                  : status === 'completed'
                  ? '1px solid rgba(16, 185, 129, 0.35)'
                  : '1px solid var(--border-dim)',
                boxShadow: status === 'active' ? '0 0 20px rgba(99, 102, 241, 0.2)' : 'none',
                position: 'relative',
                overflow: 'hidden'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <div style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: '10px',
                  background: status === 'active'
                    ? '#6366f1'
                    : status === 'completed'
                    ? '#10b981'
                    : 'rgba(255, 255, 255, 0.05)',
                  color: '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  {status === 'active' ? <Loader2 size={18} className="pulsing" /> : stage.icon}
                </div>
                
                <span style={{
                  fontSize: '0.675rem',
                  fontWeight: '700',
                  textTransform: 'uppercase',
                  padding: '2px 8px',
                  borderRadius: '6px',
                  fontFamily: 'var(--font-mono)',
                  background: status === 'completed'
                    ? 'rgba(16, 185, 129, 0.2)'
                    : status === 'active'
                    ? 'rgba(99, 102, 241, 0.25)'
                    : 'rgba(255, 255, 255, 0.05)',
                  color: status === 'completed' ? '#34d399' : status === 'active' ? '#818cf8' : '#64748b'
                }}>
                  {status === 'completed' ? 'DONE' : status === 'active' ? 'ACTIVE' : 'STANDBY'}
                </span>
              </div>

              <h4 style={{ fontSize: '0.875rem', fontWeight: '700', color: '#ffffff', marginBottom: '4px' }}>
                {stage.title}
              </h4>
              <p style={{ fontSize: '0.75rem', color: '#94a3b8', lineHeight: '1.4' }}>
                {stage.description}
              </p>
            </div>
          );
        })}
      </div>

      {/* Completion Banner */}
      {isCompleted && (
        <div className="card-container" style={{
          padding: '24px',
          background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(6, 182, 212, 0.1) 100%)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          marginBottom: '32px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '16px'
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <CheckCircle2 size={24} color="#34d399" />
              <h3 style={{ fontSize: '1.125rem', fontWeight: '800', color: '#ffffff' }}>
                Scholarship Research & Verification Complete
              </h3>
            </div>
            <p style={{ fontSize: '0.875rem', color: '#cbd5e1', marginTop: '4px' }}>
              Evaluated {summaryData?.opportunityCount ?? 0} candidate programs • Identified {summaryData?.top5Count ?? 0} high-confidence Top-5 recommendations backed by T4 official-provider evidence.
            </p>
          </div>

          <button
            onClick={onResearchFinished}
            className="btn btn-primary"
            id="view-results-btn"
            style={{ padding: '12px 24px', fontSize: '0.9375rem' }}
          >
            View Verified Opportunities <ArrowRight size={18} />
          </button>
        </div>
      )}

      {/* Live Event Stream Terminal */}
      <div className="card-container" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', borderBottom: '1px solid var(--border-dim)', paddingBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Terminal size={18} color="#818cf8" />
            <span style={{ fontSize: '0.875rem', fontWeight: '700', color: '#ffffff' }}>
              Pipeline Event Ledger
            </span>
            <span style={{
              fontSize: '0.7rem',
              fontFamily: 'var(--font-mono)',
              background: 'rgba(255, 255, 255, 0.06)',
              padding: '2px 6px',
              borderRadius: '4px',
              color: '#94a3b8'
            }}>
              {events.length} events
            </span>
          </div>

          {isRunning && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: '#818cf8' }}>
              <Loader2 size={14} className="pulsing" /> Polling live events...
            </div>
          )}
        </div>

        <div style={{
          maxHeight: '360px',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
          paddingRight: '6px',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8125rem'
        }}>
          {events.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '32px', color: '#64748b' }}>
              Initializing pipeline dispatch...
            </div>
          ) : (
            events.map((evt) => {
              const timeStr = evt.created_at ? new Date(evt.created_at).toLocaleTimeString() : '';
              return (
                <div
                  key={evt.event_id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '12px',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    background: 'rgba(0, 0, 0, 0.25)',
                    border: '1px solid rgba(255, 255, 255, 0.04)'
                  }}
                >
                  <span style={{ color: '#64748b', fontSize: '0.75rem', minWidth: '65px' }}>
                    {timeStr}
                  </span>

                  <span style={{
                    fontSize: '0.7rem',
                    fontWeight: '700',
                    padding: '1px 6px',
                    borderRadius: '4px',
                    background: evt.agent === 'EEVA' 
                      ? 'rgba(6, 182, 212, 0.2)' 
                      : evt.agent === 'MRA' 
                      ? 'rgba(99, 102, 241, 0.2)' 
                      : evt.agent === 'ASA'
                      ? 'rgba(16, 185, 129, 0.2)'
                      : 'rgba(255, 255, 255, 0.08)',
                    color: evt.agent === 'EEVA'
                      ? '#38bdf8'
                      : evt.agent === 'MRA'
                      ? '#818cf8'
                      : evt.agent === 'ASA'
                      ? '#34d399'
                      : '#cbd5e1',
                    minWidth: '55px',
                    textAlign: 'center'
                  }}>
                    {evt.agent}
                  </span>

                  <div style={{ flex: 1 }}>
                    <p style={{ color: '#e2e8f0', lineHeight: '1.4' }}>{evt.message}</p>
                    {evt.payload && Object.keys(evt.payload).length > 0 && (
                      <p style={{ fontSize: '0.7rem', color: '#64748b', marginTop: '2px' }}>
                        {JSON.stringify(evt.payload)}
                      </p>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

    </div>
  );
};
