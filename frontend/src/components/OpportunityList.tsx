import React, { useState } from 'react';
import { 
  CheckCircle2, 
  AlertCircle, 
  ExternalLink, 
  Calendar, 
  ShieldCheck, 
  Filter, 
  HelpCircle, 
  AlertTriangle,
  ArrowUpDown,
  Search as SearchIcon,
  Award,
  ChevronDown,
  ChevronUp,
  FileText
} from 'lucide-react';
import type { VerificationTier, VerifiedOpportunity } from '../types';

interface OpportunityListProps {
  opportunities: VerifiedOpportunity[];
  preferredCountries?: string[];
  onSelectForSop?: (opp: VerifiedOpportunity) => void;
  onRefresh?: () => void;
}

export const OpportunityList: React.FC<OpportunityListProps> = ({
  opportunities,
  preferredCountries = [],
  onSelectForSop,
}) => {
  const [selectedGroup, setSelectedGroup] = useState<string>('all');
  const [selectedTier, setSelectedTier] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy, setSortBy] = useState<'score' | 'deadline' | 'rank'>('score');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Top-5 Recommendations: strictly rank != null and rank <= 5
  // Note: Backend MRA assigns rank 1..5 only to T4 official-provider opportunities
  const top5Recommendations = opportunities
    .filter((o) => o.rank !== null && o.rank !== undefined && o.rank <= 5)
    .sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));

  // Filtered Secondary / All Opportunities
  const filteredOpportunities = opportunities.filter((o) => {
    if (selectedGroup !== 'all' && o.result_group !== selectedGroup) return false;
    if (selectedTier !== 'all' && o.verification_tier !== selectedTier) return false;
    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase();
      const matchText = `${o.program_name} ${o.institution} ${o.country || ''} ${o.funding_amount_text || ''}`.toLowerCase();
      if (!matchText.includes(term)) return false;
    }
    return true;
  });

  // Sort
  filteredOpportunities.sort((a, b) => {
    if (sortBy === 'score') {
      return (b.total_score ?? 0) - (a.total_score ?? 0);
    }
    if (sortBy === 'deadline') {
      const dlA = a.effective_scholarship_deadline || a.application_deadline || '9999-99-99';
      const dlB = b.effective_scholarship_deadline || b.application_deadline || '9999-99-99';
      return dlA.localeCompare(dlB);
    }
    if (sortBy === 'rank') {
      return (a.rank ?? 999) - (b.rank ?? 999);
    }
    return 0;
  });

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const renderTierBadge = (tier: VerificationTier, isMock?: boolean) => {
    if (isMock) {
      return (
        <span className="badge badge-mock" title="Candidate originated from local mock pool for testing and demonstration.">
          Illustrative Mock Record
        </span>
      );
    }
    switch (tier) {
      case 'T4':
        return <span className="badge badge-t4"><ShieldCheck size={12} /> T4 Official Verified</span>;
      case 'T3':
        return <span className="badge badge-t3">T3 Requirements Extracted</span>;
      case 'T2':
        return <span className="badge badge-t2">T2 Source Accessible</span>;
      case 'T1':
      default:
        return <span className="badge badge-t1">T1 Discovered</span>;
    }
  };

  const renderEligibilityBadge = (status: string, label: string, isScaleConversion: boolean = false) => {
    if (status === 'eligible') {
      return <span className="badge badge-eligible"><CheckCircle2 size={12} /> {label}: Confirmed Eligible</span>;
    }
    if (status === 'ineligible') {
      return <span className="badge badge-ineligible"><AlertCircle size={12} /> {label}: Ineligible</span>;
    }
    if (isScaleConversion) {
      return (
        <span className="badge badge-unknown" style={{ background: 'rgba(245, 158, 11, 0.12)', color: '#fbbf24', border: '1px solid rgba(245, 158, 11, 0.35)' }}>
          <HelpCircle size={12} /> {label}: Conversion Required
        </span>
      );
    }
    return <span className="badge badge-unknown"><HelpCircle size={12} /> {label}: Not Confirmed</span>;
  };

  const renderOpportunityCard = (opp: VerifiedOpportunity, isTop5: boolean = false) => {
    const isExpanded = expandedId === opp.opportunity_id;
    const isLiveSearch = opp.is_mock === false && (opp.search_provider === 'tavily' || opp.search_provider === 'serper');

    // Scale conversion detection: separate neutral conversion required from confirmed failures
    const isScaleConversion = Boolean(
      opp.scale_conversion_required ||
      opp.missing_student_fields?.includes('official_cgpa_conversion') ||
      (opp.admission_eligible === 'unknown' && opp.admission_ineligible_reasons?.some((r: string) => r.toLowerCase().includes('mismatch') || r.toLowerCase().includes('conversion')))
    );

    const confirmedAdmissionFailures = (opp.admission_ineligible_reasons || []).filter(
      (r: string) => !r.toLowerCase().includes('mismatch') && !r.toLowerCase().includes('conversion')
    );
    const confirmedScholarshipFailures = opp.scholarship_ineligible_reasons || [];
    const unresolvedProfileFields = (opp.missing_student_fields || []).filter(
      (f: string) => f !== 'official_cgpa_conversion'
    );

    return (
      <div
        key={opp.opportunity_id}
        className={`card-container ${isTop5 ? 'card-elevated' : ''}`}
        style={{
          padding: '24px',
          marginBottom: '16px',
          borderLeft: isTop5 ? '4px solid #6366f1' : '1px solid var(--border-dim)'
        }}
      >
        {/* Top Badges & Provenance Bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {opp.rank !== null && opp.rank !== undefined && opp.rank <= 5 && (
              <span style={{
                background: 'linear-gradient(135deg, #6366f1 0%, #4338ca 100%)',
                color: '#ffffff',
                fontWeight: '800',
                fontSize: '0.75rem',
                padding: '3px 10px',
                borderRadius: '6px',
                fontFamily: 'var(--font-mono)'
              }}>
                TOP RECOMMENDATION #{opp.rank}
              </span>
            )}

            {renderTierBadge(opp.verification_tier, opp.is_mock)}

            {/* Strict Truthfulness: Mock vs Live Search hit */}
            {isLiveSearch ? (
              <span className="badge badge-live" title={`Discovered via verified live ${opp.search_provider} search execution.`}>
                LIVE SEARCH HIT
              </span>
            ) : (
              <span className="badge badge-mock" title="Candidate originated from local mock search pool for development/offline testing.">
                MOCK SEARCH HIT
              </span>
            )}

            {/* Source Type Badge */}
            <span style={{
              fontSize: '0.7rem',
              color: opp.is_mock ? '#fbbf24' : '#94a3b8',
              fontFamily: 'var(--font-mono)',
              background: 'rgba(255, 255, 255, 0.04)',
              padding: '2px 8px',
              borderRadius: '4px',
              border: '1px solid var(--border-dim)'
            }}>
              Source: {opp.is_mock ? 'Illustrative Mock Data' : opp.source_type.replace('_', ' ')}
            </span>
          </div>

          {/* Overall Match Score */}
          {opp.total_score !== null && opp.total_score !== undefined && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Match Score:</span>
              <span style={{
                fontSize: '1.125rem',
                fontWeight: '800',
                color: opp.total_score >= 70 ? '#34d399' : opp.total_score >= 45 ? '#fbbf24' : '#94a3b8',
                fontFamily: 'var(--font-mono)'
              }}>
                {Math.round(opp.total_score)}/100
              </span>
            </div>
          )}
        </div>

        {/* Title & Institution */}
        <div style={{ marginBottom: '14px' }}>
          <h3 style={{ fontSize: '1.25rem', fontWeight: '800', color: '#ffffff', letterSpacing: '-0.01em', marginBottom: '4px' }}>
            {opp.program_name}
          </h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', fontSize: '0.875rem', color: '#cbd5e1' }}>
            <span style={{ fontWeight: '600', color: '#818cf8' }}>{opp.institution}</span>
            {opp.country && (
              <span style={{
                color: '#38bdf8',
                background: 'rgba(56, 189, 248, 0.1)',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                padding: '1px 8px',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontWeight: '600'
              }}>
                Study Destination: {opp.country}
              </span>
            )}
            {opp.degree_level && <span style={{ color: '#94a3b8' }}>• {opp.degree_level.toUpperCase()}</span>}
          </div>
        </div>

        {/* Eligibility Grid & Cycle Status */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '12px',
          padding: '14px',
          borderRadius: '10px',
          background: 'rgba(0, 0, 0, 0.3)',
          border: '1px solid var(--border-dim)',
          marginBottom: '16px'
        }}>
          <div>
            <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>ADMISSION ELIGIBILITY</span>
            {renderEligibilityBadge(opp.admission_eligible, 'Admission', isScaleConversion)}
          </div>

          <div>
            <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>SCHOLARSHIP ELIGIBILITY</span>
            {renderEligibilityBadge(opp.scholarship_eligible, 'Funding', false)}
          </div>

          <div>
            <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>APPLICATION CYCLE</span>
            <span style={{
              fontSize: '0.8125rem',
              fontWeight: '600',
              color: opp.cycle_status === 'current' ? '#34d399' : opp.cycle_status === 'expired' ? '#fb7185' : '#cbd5e1'
            }}>
              {opp.cycle_status === 'current' ? '● Open / Active Intake' : opp.cycle_status === 'expired' ? '✕ Cycle Expired (Closed)' : '? Unstated / Uncertain'}
            </span>
          </div>

          <div>
            <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>FUNDING PACKAGE</span>
            <span style={{ fontSize: '0.8125rem', fontWeight: '600', color: '#e2e8f0' }}>
              {opp.funding_coverage ? opp.funding_coverage.replace('_', ' ').toUpperCase() : 'UNKNOWN'}
            </span>
          </div>
        </div>

        {/* Academic Requirements (CGPA & Tests with explicit scale) */}
        {(opp.min_cgpa !== null && opp.min_cgpa !== undefined || opp.english_min_score || (opp.gre_required !== null && opp.gre_required !== undefined)) && (
          <div style={{
            display: 'flex',
            gap: '20px',
            flexWrap: 'wrap',
            marginBottom: '14px',
            fontSize: '0.8125rem',
            background: 'rgba(255, 255, 255, 0.02)',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid var(--border-dim)'
          }}>
            {opp.min_cgpa !== null && opp.min_cgpa !== undefined && (
              <div>
                <span style={{ color: '#94a3b8' }}>Minimum Grade / CGPA: </span>
                <strong style={{ color: '#ffffff', fontFamily: 'var(--font-mono)' }}>
                  {opp.min_cgpa} {opp.cgpa_scale ? `/ ${opp.cgpa_scale}` : '(Scale: Unknown / Unstated)'}
                </strong>
              </div>
            )}
            {opp.english_min_score && (
              <div>
                <span style={{ color: '#94a3b8' }}>English Requirement: </span>
                <strong style={{ color: '#ffffff' }}>
                  {opp.english_test || 'Language Test'}: {opp.english_min_score}
                </strong>
              </div>
            )}
            {opp.gre_required !== null && opp.gre_required !== undefined && (
              <div>
                <span style={{ color: '#94a3b8' }}>GRE: </span>
                <strong style={{ color: '#ffffff' }}>
                  {opp.gre_required ? 'Mandatory' : 'Not Required'}
                </strong>
              </div>
            )}
          </div>
        )}

        {/* Deadlines Section (Separating Scholarship vs Admission) */}
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', marginBottom: '16px', fontSize: '0.8125rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#cbd5e1' }}>
            <Calendar size={15} color="#818cf8" />
            <span style={{ color: '#94a3b8' }}>Scholarship Cutoff:</span>
            <strong style={{ color: opp.effective_scholarship_deadline ? '#ffffff' : '#94a3b8' }}>
              {opp.effective_scholarship_deadline ? `${opp.effective_scholarship_deadline}${opp.is_mock ? ' (Illustrative example)' : ''}` : 'Not stated on portal'}
            </strong>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#cbd5e1' }}>
            <Calendar size={15} color="#06b6d4" />
            <span style={{ color: '#94a3b8' }}>Admission Cutoff:</span>
            <strong style={{ color: opp.effective_admission_deadline ? '#ffffff' : '#94a3b8' }}>
              {opp.effective_admission_deadline ? `${opp.effective_admission_deadline}${opp.is_mock ? ' (Illustrative example)' : ''}` : 'Department rolling'}
            </strong>
          </div>
        </div>

        {/* 1. Neutral Grading Scale Conversion Notice (Amber / Blue, NEVER Red!) */}
        {isScaleConversion && (
          <div style={{
            padding: '12px 14px',
            borderRadius: '8px',
            background: 'rgba(245, 158, 11, 0.08)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            marginBottom: '16px',
            fontSize: '0.8125rem'
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', color: '#fbbf24', marginBottom: '6px' }}>
              <HelpCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
              <div>
                <strong style={{ color: '#ffffff' }}>Eligibility Status: Not Confirmed (Official Grading Scale Conversion Required)</strong>
                <p style={{ margin: '4px 0 0', color: '#cbd5e1', lineHeight: '1.45' }}>
                  {opp.scale_conversion_explanation ||
                    `Your submitted grade scale differs from the program requirement scale (Student grade compared with program minimum ${opp.min_cgpa ? `${opp.min_cgpa}/${opp.cgpa_scale || 4.0}` : ''}). Direct mathematical conversion (such as multiplying by 10 or linear scaling) is not valid without an official institutional evaluation.`}
                </p>
              </div>
            </div>
            <div style={{
              fontSize: '0.75rem',
              color: '#94a3b8',
              background: 'rgba(0, 0, 0, 0.25)',
              padding: '6px 10px',
              borderRadius: '6px',
              marginTop: '8px',
              border: '1px solid var(--border-dim)'
            }}>
              <strong>What you can do next:</strong> Obtain an official academic credential evaluation report (e.g. WES, ECE, or a registrar-issued institutional equivalency certificate) to confirm equivalency before formal application.
            </div>
          </div>
        )}

        {/* 2. Confirmed Ineligibility Failures (Strictly RED, only for confirmed failures) */}
        {((opp.admission_eligible === 'ineligible' && confirmedAdmissionFailures.length > 0) ||
          (opp.scholarship_eligible === 'ineligible' && confirmedScholarshipFailures.length > 0)) && (
          <div style={{
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'rgba(244, 63, 94, 0.08)',
            border: '1px solid rgba(244, 63, 94, 0.25)',
            marginBottom: '16px',
            fontSize: '0.8125rem'
          }}>
            {opp.admission_eligible === 'ineligible' && confirmedAdmissionFailures.map((r, i) => (
              <p key={`adm-${i}`} style={{ color: '#fb7185', display: 'flex', alignItems: 'center', gap: '6px', margin: '2px 0' }}>
                <AlertCircle size={14} /> <strong>Admission Ineligibility:</strong> {r}
              </p>
            ))}
            {opp.scholarship_eligible === 'ineligible' && confirmedScholarshipFailures.map((r, i) => (
              <p key={`schol-${i}`} style={{ color: '#fb7185', display: 'flex', alignItems: 'center', gap: '6px', margin: '2px 0' }}>
                <AlertCircle size={14} /> <strong>Scholarship Ineligibility:</strong> {r}
              </p>
            ))}
          </div>
        )}

        {/* 3. Missing Fields Notice */}
        {unresolvedProfileFields.length > 0 && (
          <div style={{
            padding: '8px 12px',
            borderRadius: '6px',
            background: 'rgba(245, 158, 11, 0.06)',
            border: '1px solid rgba(245, 158, 11, 0.2)',
            marginBottom: '16px',
            fontSize: '0.75rem',
            color: '#fbbf24',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}>
            <AlertTriangle size={14} /> <strong>Missing profile fields to confirm eligibility:</strong> {unresolvedProfileFields.join(', ')}
          </div>
        )}

        {/* Verbatim Official Evidence Excerpt or Mock Demonstration */}
        {opp.evidence_excerpt && (
          <div style={{
            padding: '12px 14px',
            borderRadius: '8px',
            background: opp.is_mock ? 'rgba(245, 158, 11, 0.05)' : 'rgba(99, 102, 241, 0.06)',
            border: opp.is_mock ? '1px solid rgba(245, 158, 11, 0.2)' : '1px solid rgba(99, 102, 241, 0.2)',
            marginBottom: '16px',
            fontSize: '0.8125rem'
          }}>
            <span style={{
              fontSize: '0.7rem',
              fontWeight: '700',
              color: opp.is_mock ? '#fbbf24' : (opp.verification_tier === 'T4' ? '#34d399' : '#818cf8'),
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
              display: 'block',
              marginBottom: '4px'
            }}>
              {opp.is_mock
                ? 'Illustrative Opportunity Summary (Unverified Mock Record):'
                : (opp.verification_tier === 'T4'
                  ? 'Verbatim Official Evidence Excerpt (T4 Grounding):'
                  : `Extracted Evidence Snippet (Tier ${opp.verification_tier}):`)}
            </span>
            <p style={{ color: '#e2e8f0', fontStyle: 'italic', lineHeight: '1.45' }}>
              "{opp.evidence_excerpt}"
            </p>
          </div>
        )}

        {/* Expandable MRA Score Breakdown & Rationale */}
        {isExpanded && opp.score_breakdown && (
          <div style={{
            padding: '16px',
            borderRadius: '10px',
            background: 'rgba(0, 0, 0, 0.4)',
            border: '1px solid var(--border-dim)',
            marginBottom: '16px',
            fontSize: '0.8125rem'
          }}>
            <h4 style={{ fontSize: '0.875rem', fontWeight: '700', color: '#ffffff', marginBottom: '10px' }}>
              MRA Score Factor Breakdown (Deterministic 0-100)
            </h4>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '10px', marginBottom: '14px' }}>
              {Object.entries(opp.score_breakdown).map(([factor, score]) => (
                <div key={factor} style={{ background: 'rgba(255, 255, 255, 0.04)', padding: '8px 10px', borderRadius: '6px' }}>
                  <span style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', display: 'block' }}>
                    {factor.replace('_', ' ')}
                  </span>
                  <strong style={{ fontSize: '0.9375rem', color: '#ffffff', fontFamily: 'var(--font-mono)' }}>
                    {score} pts
                  </strong>
                </div>
              ))}
            </div>

            {opp.recommendation_rationale && (
              <div style={{ borderTop: '1px solid var(--border-dim)', paddingTop: '10px' }}>
                <span style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', display: 'block', marginBottom: '4px' }}>
                  Matchmaking Rationale & Transparency
                </span>
                <p style={{ color: '#cbd5e1', lineHeight: '1.4' }}>
                  {opp.recommendation_rationale}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Card Footer Actions */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', borderTop: '1px solid var(--border-dim)', paddingTop: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <a
              href={opp.official_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '6px 12px' }}
              title={opp.is_mock ? 'Direct link to program authority page (Illustrative mock link)' : 'Official program authority website'}
            >
              Official Portal <ExternalLink size={13} />
            </a>

            {opp.score_breakdown && (
              <button
                type="button"
                onClick={() => toggleExpand(opp.opportunity_id)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#94a3b8',
                  fontSize: '0.75rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px'
                }}
              >
                {isExpanded ? <>Less Details <ChevronUp size={14} /></> : <>Score Breakdown <ChevronDown size={14} /></>}
              </button>
            )}
          </div>

          {onSelectForSop && (
            <button
              onClick={() => onSelectForSop(opp)}
              className="btn btn-primary"
              style={{ fontSize: '0.75rem', padding: '8px 16px' }}
            >
              <FileText size={14} /> Review Strategy & SOP
            </button>
          )}
        </div>

      </div>
    );
  };

  return (
    <div style={{ maxWidth: '1180px', margin: '32px auto', padding: '0 16px' }}>
      
      {/* Top Banner */}
      <div style={{ marginBottom: '28px' }}>
        <h2 style={{ fontSize: '1.75rem', fontWeight: '800', color: '#ffffff', letterSpacing: '-0.02em' }}>
          Evaluated Scholarship Opportunities
        </h2>
        <p style={{ color: '#94a3b8', fontSize: '0.9375rem', marginTop: '4px' }}>
          {opportunities.length > 0 && opportunities.every((o) => !o.is_mock && o.verification_tier === 'T4')
            ? 'All opportunities are grounded in official primary sources.'
            : 'Opportunities evaluated via autonomous research and multi-tier evidence verification. Results are categorized by deterministic eligibility and evidence tier.'}
        </p>
      </div>

      {/* Filter and Control Bar */}
      <div className="card-container" style={{ padding: '16px 20px', marginBottom: '28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
          
          {/* Keyword Search */}
          <div style={{ position: 'relative', flex: '1 1 240px', minWidth: '200px' }}>
            <SearchIcon size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: '#94a3b8' }} />
            <input
              type="text"
              className="form-input"
              style={{ paddingLeft: '36px', fontSize: '0.875rem' }}
              placeholder="Filter by university, title, country..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>

          {/* Group Filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Filter size={15} color="#94a3b8" />
            <select
              className="form-select"
              style={{ padding: '8px 12px', fontSize: '0.8125rem' }}
              value={selectedGroup}
              onChange={(e) => setSelectedGroup(e.target.value)}
            >
              <option value="all">All Eligibility Groups</option>
              <option value="confirmed_eligible">Confirmed Eligible (Group 1)</option>
              <option value="potentially_eligible">Potentially Eligible (Group 2)</option>
              <option value="ineligible">Ineligible (Excluded)</option>
              <option value="expired">Expired Intake</option>
            </select>
          </div>

          {/* Tier Filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <select
              className="form-select"
              style={{ padding: '8px 12px', fontSize: '0.8125rem' }}
              value={selectedTier}
              onChange={(e) => setSelectedTier(e.target.value)}
            >
              <option value="all">All Evidence Tiers</option>
              <option value="T4">Tier 4 (Official Verified)</option>
              <option value="T3">Tier 3 (Requirements Extracted)</option>
              <option value="T2">Tier 2 (Source Accessible)</option>
              <option value="T1">Tier 1 (Discovered / Unverified)</option>
            </select>
          </div>

          {/* Sort By */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ArrowUpDown size={15} color="#94a3b8" />
            <select
              className="form-select"
              style={{ padding: '8px 12px', fontSize: '0.8125rem' }}
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
            >
              <option value="score">Sort by Match Score</option>
              <option value="rank">Sort by Top Recommendation Rank</option>
              <option value="deadline">Sort by Deadline</option>
            </select>
          </div>

        </div>
      </div>

      {/* SECTION 1: TOP-5 RECOMMENDATIONS (Strict T4 + Official-Provider) */}
      <div style={{ marginBottom: '40px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          <Award size={20} color="#6366f1" />
          <h3 style={{ fontSize: '1.25rem', fontWeight: '800', color: '#ffffff' }}>
            Top Recommended Opportunities ({top5Recommendations.length})
          </h3>
          <span style={{
            fontSize: '0.7rem',
            fontFamily: 'var(--font-mono)',
            padding: '2px 8px',
            borderRadius: '4px',
            background: 'rgba(99, 102, 241, 0.15)',
            color: '#818cf8',
            border: '1px solid rgba(99, 102, 241, 0.3)'
          }}>
            Strict T4 Primary Source Rule Enforced
          </span>
        </div>

        {top5Recommendations.length === 0 ? (
          <div className="card-container" style={{ padding: '32px', textAlign: 'center', color: '#94a3b8' }}>
            <AlertCircle size={32} color="#f59e0b" style={{ margin: '0 auto 12px' }} />
            <h4 style={{ fontSize: '1rem', fontWeight: '700', color: '#ffffff', marginBottom: '6px' }}>
              {preferredCountries.length > 0
                ? `No verified opportunities found for this destination yet (${preferredCountries.join(', ')})`
                : 'No Fully Verified T4 Primary-Source Opportunities in Top-5'}
            </h4>
            <p style={{ fontSize: '0.875rem', maxWidth: '640px', margin: '0 auto', lineHeight: '1.5' }}>
              {preferredCountries.length > 0
                ? `Recommendations are strictly limited to verified programs officially available for study in ${preferredCountries.join(', ')}. In offline development mode, only illustrative mock examples are available. Live search requires configured search provider credentials (e.g. Tavily/Serper). We never silently substitute opportunities from other countries.`
                : 'Under ScholarSwarm AI rules, lower-tier (T1–T3) or unverified mock results are strictly excluded from Top-5 recommendations. Review evaluated candidates below.'}
            </p>
          </div>
        ) : (
          <div>
            {top5Recommendations.map((opp) => renderOpportunityCard(opp, true))}
          </div>
        )}
      </div>

      {/* SECTION 2: ALL / FILTERED DISCOVERIES */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <h3 style={{ fontSize: '1.125rem', fontWeight: '800', color: '#ffffff' }}>
            All Evaluated Candidates ({filteredOpportunities.length})
          </h3>
        </div>

        {filteredOpportunities.length === 0 ? (
          <div className="card-container" style={{ padding: '32px', textAlign: 'center', color: '#94a3b8' }}>
            <p style={{ fontSize: '0.9375rem', color: '#ffffff', marginBottom: '6px' }}>
              {preferredCountries.length > 0
                ? `No verified opportunities found for this destination yet (${preferredCountries.join(', ')}).`
                : 'No opportunities match the selected filters.'}
            </p>
            <p style={{ fontSize: '0.8125rem', color: '#94a3b8', maxWidth: '580px', margin: '0 auto', lineHeight: '1.45' }}>
              ScholarSwarm AI does not invent scholarships or substitute programs from unintended countries. When live search is configured, real-time discovery queries this destination.
            </p>
          </div>
        ) : (
          filteredOpportunities.map((opp) => renderOpportunityCard(opp, false))
        )}
      </div>

    </div>
  );
};
