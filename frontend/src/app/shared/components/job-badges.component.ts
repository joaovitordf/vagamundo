import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ScreeningResult } from '../../core/models/vaga.model';
import { FIT_THRESHOLDS } from '../../core/utils/job-filters.util';

@Component({
  selector: 'app-job-badges',
  standalone: true,
  imports: [CommonModule],
  styles: [`
    :host {
      display: inline-flex;
      flex-wrap: wrap;
      max-width: 100%;
      min-width: 0;
      flex: 0 1 auto;
    }
  `],
  template: `
    @if (hasContent()) {
      <div [class]="containerClass">
        @if (autoPromoted) {
          <span class="badge-auto-promoted"
                [title]="autoOrigin === 'recruiter' ? 'Promovida automaticamente pelo Modo Automático (Recrutadores)' : 'Promovida automaticamente pelo Modo Automático'">
            <i class="bi bi-robot"></i> Auto{{ autoOrigin === 'recruiter' ? ' · Recrutador' : '' }}
          </span>
        }
        @if (resolvedModel(); as model) {
          <span class="vc-badge-model" [title]="modelTitle">
            <i class="bi bi-cpu"></i> {{ model }}
          </span>
        }
        @if (resolvedScore() !== null && resolvedScore() !== undefined) {
          <span class="vc-badge-fit"
            [class.vc-badge-fit--high]="resolvedScore()! >= thresholds.high"
            [class.vc-badge-fit--med]="resolvedScore()! >= thresholds.medium && resolvedScore()! < thresholds.high"
            [class.vc-badge-fit--low]="resolvedScore()! < thresholds.medium"
            [title]="scoreTitle()">
            {{ resolvedScore() }}/100 &bull; {{ resolvedVerdict() }}
          </span>
        }
        @if (screening?.language_gate === 'FLAG' || screening?.language_gate === 'FAIL') {
          <span class="vc-badge-gate"
                [class.vc-badge-gate--fail]="screening?.language_gate === 'FAIL'"
                [title]="screening?.language_note || 'Exigência de idioma a verificar'">
            <i class="bi bi-translate"></i> Idioma: {{ screening!.language_gate }}
          </span>
        }
        @if (screening?.location_verdict === 'FLAG' || screening?.location_verdict === 'FAIL') {
          <span class="vc-badge-gate"
                [class.vc-badge-gate--fail]="screening?.location_verdict === 'FAIL'"
                title="Restrição de localidade, modalidade presencial/híbrida ou elegibilidade internacional">
            <i class="bi bi-geo-alt"></i> Local: {{ screening!.location_verdict }}
          </span>
        }
      </div>
    }
  `,
})
export class JobBadgesComponent {
  @Input() screening?: ScreeningResult | null;
  @Input() aiModel?: string | null;
  @Input() score?: number | null;
  @Input() verdict?: string | null;
  @Input() autoPromoted = false;
  @Input() autoOrigin?: string | null;
  @Input() containerClass = 'vc-badge-stack';
  @Input() modelTitle = 'Modelo de IA que gerou esta triagem';

  readonly thresholds = FIT_THRESHOLDS;

  resolvedModel(): string | null {
    return this.screening?.ai_model || this.aiModel || null;
  }

  resolvedScore(): number | null {
    const val = this.screening?.score ?? this.score;
    return typeof val === 'number' ? val : null;
  }

  resolvedVerdict(): string {
    const sc = this.resolvedScore() ?? 0;
    return (
      this.screening?.verdict ||
      this.verdict ||
      (sc >= FIT_THRESHOLDS.high ? 'Alta Afinidade' : sc >= FIT_THRESHOLDS.medium ? 'Média Afinidade' : 'Baixa Afinidade')
    );
  }

  scoreTitle(): string {
    const s = this.screening?.subscores;
    if (s) {
      return `Téc: ${s.technical} · Exp: ${s.experience} · Comp: ${s.behavioral} · Carr: ${s.career}`;
    }
    return 'Afinidade calculada na rubrica 30/25/15/30';
  }

  hasContent(): boolean {
    return Boolean(
      this.autoPromoted ||
      this.resolvedModel() ||
      this.resolvedScore() !== null ||
      this.screening?.language_gate === 'FLAG' ||
      this.screening?.language_gate === 'FAIL' ||
      this.screening?.location_verdict === 'FLAG' ||
      this.screening?.location_verdict === 'FAIL'
    );
  }
}
