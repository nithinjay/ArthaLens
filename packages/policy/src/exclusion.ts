/**
 * Jio IPO exclusion matcher (ADR-0008).
 *
 * The rules live in ../exclusions.v1.json and the expected behaviour in
 * ../exclusion-vectors.v1.json. ai/arthalens_ai/policy/exclusion.py implements the same
 * algorithm; both must pass the same vectors. Change the algorithm in both places at once.
 *
 * Decisions fail closed: anything that merely *looks like* an excluded name is quarantined,
 * which blocks every workflow just like an exclusion does.
 */
import { readFileSync } from 'node:fs';

export type Decision = 'allowed' | 'excluded' | 'quarantined';
export type Reason = 'identifier' | 'token' | 'alias' | 'embedded' | 'confusable';
export type Scope = 'ipo' | 'stock';

export interface IdentifierSet {
  isin?: readonly string[];
  cin?: readonly string[];
  nse_symbol?: readonly string[];
  bse_code?: readonly string[];
}

export interface ExclusionRule {
  rule_id: string;
  scope: readonly Scope[];
  reason: string;
  user_message: string;
  match: {
    tokens: readonly string[];
    aliases: readonly string[];
    identifiers: Required<IdentifierSet>;
  };
}

export interface ExclusionPolicy {
  version: number;
  updated: string;
  rules: readonly ExclusionRule[];
  allow: readonly { normalized_name: string; rule_id: string; justification: string }[];
}

export interface ExclusionResult {
  decision: Decision;
  reason: Reason | null;
  rule_id: string | null;
  policy_version: number;
  /** Safe to show to users. Null when allowed. */
  user_message: string | null;
}

export interface EntityRef {
  name: string;
  identifiers?: IdentifierSet;
}

// Look-alike characters, applied only in the confusable pass (after lower-casing).
const CONFUSABLES: Readonly<Record<string, string>> = {
  '0': 'o',
  '1': 'i',
  l: 'i',
  '|': 'i',
  '!': 'i',
  '3': 'e',
  '5': 's',
  '\u0131': 'i', // dotless i
  '\u0458': 'j', // Cyrillic je
  '\u0456': 'i', // Cyrillic i
  '\u0457': 'i', // Cyrillic yi
  '\u04cf': 'i', // Cyrillic palochka
  '\u043e': 'o', // Cyrillic o
  '\u03bf': 'o', // Greek omicron
  '\u03b9': 'i', // Greek iota
  '\u0269': 'i', // Latin iota
};

const INVISIBLE = /\p{Cf}/gu; // zero-width spaces/joiners, soft hyphen, BOM, bidi marks...
const NON_ALNUM = /[^\p{L}\p{N}]+/gu;

function fold(input: string): string {
  return input.normalize('NFKC').replace(INVISIBLE, '').toLowerCase();
}

function clean(folded: string): string {
  return folded.replace(NON_ALNUM, ' ').trim().replace(/ +/g, ' ');
}

/** Canonical form used for matching and for allow-list entries. */
export function normalizeName(input: string): string {
  return clean(fold(input));
}

function confusableForm(input: string): string {
  const mapped = Array.from(fold(input), (ch) => CONFUSABLES[ch] ?? ch).join('');
  return clean(mapped);
}

function containsSequence(tokens: readonly string[], seq: readonly string[]): boolean {
  if (seq.length === 0 || seq.length > tokens.length) return false;
  outer: for (let i = 0; i <= tokens.length - seq.length; i++) {
    for (let j = 0; j < seq.length; j++) {
      if (tokens[i + j] !== seq[j]) continue outer;
    }
    return true;
  }
  return false;
}

function identifierHit(rule: ExclusionRule, ids: IdentifierSet | undefined): boolean {
  if (!ids) return false;
  const kinds = ['isin', 'cin', 'nse_symbol', 'bse_code'] as const;
  return kinds.some((kind) => {
    const wanted = new Set(rule.match.identifiers[kind].map((v) => v.toUpperCase()));
    return (ids[kind] ?? []).some((v) => wanted.has(v.trim().toUpperCase()));
  });
}

export function evaluate(
  policy: ExclusionPolicy,
  entity: EntityRef,
  scope: Scope = 'ipo',
): ExclusionResult {
  const normalized = normalizeName(entity.name);
  const tokens = normalized === '' ? [] : normalized.split(' ');
  const compact = normalized.replaceAll(' ', '');
  const confusableCompact = confusableForm(entity.name).replaceAll(' ', '');

  for (const rule of policy.rules) {
    if (!rule.scope.includes(scope)) continue;
    const hit = (decision: Decision, reason: Reason): ExclusionResult => ({
      decision,
      reason,
      rule_id: rule.rule_id,
      policy_version: policy.version,
      user_message: rule.user_message,
    });

    // Identifiers are unambiguous, so they win even over an allow entry.
    if (identifierHit(rule, entity.identifiers)) return hit('excluded', 'identifier');

    const allowed = policy.allow.some(
      (a) => a.rule_id === rule.rule_id && a.normalized_name === normalized,
    );
    if (allowed) continue;

    const ruleTokens = rule.match.tokens.map(normalizeName);
    if (tokens.some((t) => ruleTokens.includes(t))) return hit('excluded', 'token');

    for (const alias of rule.match.aliases) {
      if (containsSequence(tokens, normalizeName(alias).split(' ')))
        return hit('excluded', 'alias');
    }
    if (ruleTokens.some((t) => compact.includes(t))) return hit('quarantined', 'embedded');
    if (ruleTokens.some((t) => confusableCompact.includes(t))) {
      return hit('quarantined', 'confusable');
    }
  }

  return {
    decision: 'allowed',
    reason: null,
    rule_id: null,
    policy_version: policy.version,
    user_message: null,
  };
}

export function loadPolicy(
  url: URL = new URL('../exclusions.v1.json', import.meta.url),
): ExclusionPolicy {
  const policy = JSON.parse(readFileSync(url, 'utf8')) as ExclusionPolicy;
  if (policy.version !== 1 || !Array.isArray(policy.rules) || policy.rules.length === 0) {
    // Fail closed: a missing or malformed policy must stop the service, not disable the rule.
    throw new Error('Exclusion policy is missing or malformed');
  }
  return policy;
}
