import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { Vaga } from '../../../core/models/vaga.model';
import { JobBadgesComponent } from '../../../shared/components/job-badges.component';
import { PortalBadgeComponent } from '../../../shared/components/portal-badge.component';
import {
  formatSalaryBRL,
  getJobWarning,
  getPortalDisplayName,
  getWorkModelLabel,
  hasVisaSponsorship,
  isJobUndated,
} from '../../../core/utils/job-filters.util';

@Component({
  selector: 'app-buscar-job-card',
  standalone: true,
  imports: [JobBadgesComponent, PortalBadgeComponent],
  templateUrl: './buscar-job-card.component.html',
  styleUrl: './buscar-job-card.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BuscarJobCardComponent {
  @Input({ required: true }) vaga!: Vaga;
  @Input() selectable = false;
  @Input() selected = false;
  @Input() showSummary = true;
  @Input() showExtendedChips = true;
  @Input() externalLinkLabel = 'Ver no portal';

  @Output() selectedChange = new EventEmitter<Event>();
  @Output() interesse = new EventEmitter<Vaga>();
  @Output() applied = new EventEmitter<Vaga>();
  @Output() descartar = new EventEmitter<Vaga>();

  readonly getPortalName = getPortalDisplayName;
  readonly getModelLabel = getWorkModelLabel;
  readonly formatSalaryBRL = formatSalaryBRL;
  readonly hasVisa = hasVisaSponsorship;
  readonly isUndated = isJobUndated;
  readonly getWarning = getJobWarning;
}
