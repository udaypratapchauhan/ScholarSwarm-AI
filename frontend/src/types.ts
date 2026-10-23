/**
 * TypeScript data models and type definitions for ScholarSwarm AI.
 * Strict 1-to-1 mapping with backend Pydantic schemas.
 */

export type DegreeLevel = 'undergraduate' | 'masters' | 'phd' | 'postdoc';

export type VerificationTier = 'T1' | 'T2' | 'T3' | 'T4';

export type EligibilityStatus = 'eligible' | 'ineligible' | 'unknown';

export type CycleStatus = 'current' | 'expired' | 'uncertain';

export type SourceType = 'official_provider' | 'reliable_secondary' | 'aggregator' | 'unknown';

export type ResultGroup = 'confirmed_eligible' | 'potentially_eligible' | 'ineligible' | 'expired';

export type AgentRole = 'SPA' | 'ORA' | 'EEVA' | 'MRA' | 'ASA' | 'SYSTEM';

export interface SkillEntry {
  skill: string;
  confidence: 'explicit' | 'inferred';
}

export interface GitHubRepo {
  name: string;
  language?: string | null;
  stars: number;
  description?: string | null;
}

export interface StudentProfile {
  session_id: string;
  name?: string | null;
  email?: string | null;
  nationality?: string | null;
  current_degree?: string | null;
  cgpa?: number | null;
  cgpa_scale?: number | null;
  ielts_score?: number | null;
  toefl_score?: number | null;
  gre_score?: number | null;
  gmat_score?: number | null;
  work_experience_years?: number | null;
  publications?: string[];
  awards?: string[];
  languages_known?: string[];
  github_repos?: GitHubRepo[];
  skills_extracted?: SkillEntry[];
  field_of_study: string;
  target_degree: DegreeLevel;
  preferred_countries?: string[];
  parse_warnings?: string[];
  parse_errors?: string[];
  created_at?: string;
}

export interface DeadlineEntry {
  deadline_type: 'scholarship' | 'admission' | 'priority_aid' | 'departmental' | 'general' | 'unknown';
  deadline_date?: string | null;
  deadline_time?: string | null;
  timezone?: string | null;
  intake_cycle?: string | null;
  raw_text: string;
  is_inferred_year: boolean;
}

export interface VerifiedOpportunity {
  opportunity_id: string;
  session_id: string;
  institution: string;
  program_name: string;
  type?: string;
  official_url: string;
  canonical_url?: string | null;
  source_type: SourceType;
  verification_tier: VerificationTier;
  page_accessible?: boolean;
  page_http_status?: number | null;
  country?: string | null;
  degree_level?: string | null;

  funding_coverage?: 'full' | 'partial' | 'unknown' | string;
  funding_amount_text?: string | null;
  min_cgpa?: number | null;
  cgpa_scale?: number | null;
  english_test?: string | null;
  english_min_score?: string | null;
  gre_required?: boolean | null;
  eligible_nationalities?: string[] | null;
  deadlines?: DeadlineEntry[];
  application_deadline?: string | null;
  effective_scholarship_deadline?: string | null;
  effective_admission_deadline?: string | null;
  cycle_status: CycleStatus;
  required_documents?: string[];
  application_instructions?: string | null;

  evidence_excerpt?: string | null;
  source_url: string;

  admission_eligible: EligibilityStatus;
  admission_ineligible_reasons?: string[];
  scholarship_eligible: EligibilityStatus;
  scholarship_ineligible_reasons?: string[];
  missing_student_fields?: string[];

  result_group: ResultGroup;
  rank?: number | null;
  total_score?: number | null;
  score_breakdown?: {
    field_alignment?: number;
    funding_coverage?: number;
    deadline_proximity?: number;
    eligibility_clarity?: number;
    data_completeness?: number;
    [key: string]: number | undefined;
  } | null;
  recommendation_rationale?: string | null;
  confidence?: 'high' | 'medium' | 'low' | null;

  // Provenance flag from backend search abstraction
  is_mock?: boolean;
  search_provider?: string;

  // Grade scale mismatch explanation
  scale_conversion_required?: boolean;
  scale_conversion_explanation?: string | null;
}

export interface SOPDraft {
  draft_id: string;
  session_id: string;
  opportunity_id: string;
  institution: string;
  program_name: string;
  sop_text: string;
  word_count: number;
  cited_profile_elements: string[];
  missing_info_prompts: string[];
  suggested_revisions: string[];
  generated_at: string;
}

export interface PipelineEvent {
  event_id: string;
  session_id: string;
  agent: AgentRole;
  event_type: string;
  message: string;
  payload?: Record<string, any>;
  created_at: string;
}

export interface SessionRecord {
  session_id: string;
  status: 'initialized' | 'running' | 'completed' | 'failed';
  student_profile?: StudentProfile | null;
  created_at: string;
  updated_at?: string;
}

export interface HealthResponse {
  status: 'healthy' | 'unhealthy';
  database: 'connected' | 'disconnected';
  version: string;
  timestamp: string;
}

export interface ResearchStartResponse {
  session_id: string;
  status: string;
  opportunity_count: number;
  top_5_count: number;
  sop_generated: boolean;
}
