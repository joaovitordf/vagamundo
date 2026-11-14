import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { getPortalDisplayName } from '../../core/utils/job-filters.util';

/**
 * Shared portal origin badge with distinctive LinkedIn branding (icon + LinkedIn blue)
 * across Recrutadores, Me Interessam, Candidaturas, Descartadas, Buscar Vagas, and Dashboard.
 */
@Component({
  selector: 'app-portal-badge',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (showBadge) {
      <span
        class="portal-badge"
        [class.portal-badge--compact]="compact"
        [class.portal-badge--linkedin]="isLinkedIn"
        [attr.data-portal]="portalKey"
        [title]="badgeTitle">
        <i [class]="iconClass" aria-hidden="true"></i>
        <span>{{ displayLabel }}</span>
      </span>
    }
  `,
  styles: [`
    :host {
      display: inline-flex;
      vertical-align: middle;
    }

    .portal-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.22rem 0.6rem;
      border-radius: 6px;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      line-height: 1.15;
      white-space: nowrap;
      background: rgba(148, 163, 184, 0.14);
      border: 1px solid rgba(148, 163, 184, 0.32);
      color: var(--text-primary, #e2e8f0);
    }

    .portal-badge--compact {
      padding: 0.14rem 0.45rem;
      font-size: 0.68rem;
      gap: 0.28rem;
      text-transform: none;
      letter-spacing: 0.01em;
    }

    .portal-badge[data-portal="linkedin_post"],
    .portal-badge[data-portal="linkedin-search"],
    .portal-badge--linkedin {
      background: rgba(10, 102, 194, 0.22);
      color: #70b5f9;
      border-color: rgba(10, 102, 194, 0.48);
    }

    .portal-badge[data-portal="github-vagas"] {
      background: rgba(148, 163, 184, 0.18);
      color: #e2e8f0;
      border-color: rgba(148, 163, 184, 0.36);
    }

    .portal-badge[data-portal="hn-search"] {
      background: rgba(251, 146, 60, 0.16);
      color: #fdba74;
      border-color: rgba(251, 146, 60, 0.4);
    }

    :host-context([data-theme="light"]) .portal-badge {
      background: rgba(100, 116, 139, 0.1);
      color: #334155;
      border-color: rgba(100, 116, 139, 0.26);
    }

    :host-context([data-theme="light"]) .portal-badge[data-portal="linkedin_post"],
    :host-context([data-theme="light"]) .portal-badge[data-portal="linkedin-search"],
    :host-context([data-theme="light"]) .portal-badge--linkedin {
      background: rgba(10, 102, 194, 0.12);
      color: #0a66c2;
      border-color: rgba(10, 102, 194, 0.34);
    }

    :host-context([data-theme="light"]) .portal-badge[data-portal="github-vagas"] {
      background: rgba(51, 65, 85, 0.1);
      color: #1e293b;
      border-color: rgba(51, 65, 85, 0.28);
    }

    :host-context([data-theme="light"]) .portal-badge[data-portal="hn-search"] {
      background: rgba(234, 88, 12, 0.1);
      color: #c2410c;
      border-color: rgba(234, 88, 12, 0.3);
    }
  `]
})
export class PortalBadgeComponent {
  @Input() portal: string | null | undefined = '';
  @Input() compact = false;
  @Input() labelOverride: string | null | undefined = null;

  get portalKey(): string {
    return String(this.portal || '').trim().toLowerCase();
  }

  get showBadge(): boolean {
    return Boolean(this.portalKey || (this.labelOverride || '').trim());
  }

  get isLinkedIn(): boolean {
    return this.portalKey === 'linkedin_post'
      || this.portalKey === 'linkedin-search'
      || this.portalKey.includes('linkedin');
  }

  get displayLabel(): string {
    const custom = (this.labelOverride || '').trim();
    if (custom) return custom;
    return getPortalDisplayName(this.portal);
  }

  get iconClass(): string {
    if (this.isLinkedIn) return 'bi bi-linkedin';
    if (this.portalKey.includes('github')) return 'bi bi-github';
    if (this.portalKey === 'hn-search' || this.portalKey === 'hn') return 'bi bi-terminal';
    if (this.portalKey === 'recruiter_email' || this.portalKey === 'recruiter_radar') return 'bi bi-envelope-paper';
    if (this.portalKey === 'manual') return 'bi bi-pencil-square';
    return 'bi bi-globe';
  }

  get badgeTitle(): string {
    return `Origem: ${this.displayLabel}`;
  }
}
