import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { CvAreasSource } from '../../../core/models/vaga.model';

@Component({
  selector: 'app-cv-random-control',
  standalone: true,
  template: `
    <div class="cv-random-group">
      <button
        type="button"
        class="btn-random-cv"
        [disabled]="disabled"
        (click)="onPickClick($event)"
        title="Sortear palavra-chave configurada no Meu perfil">
        <i class="bi bi-dice-5" aria-hidden="true"></i>
        <span>Sortear área CV</span>
      </button>

      <button
        type="button"
        class="btn-random-info"
        [class.active]="infoOpen()"
        (click)="toggleInfo($event)"
        [attr.aria-expanded]="infoOpen()"
        aria-label="Informações sobre as palavras sorteadas do CV"
        title="De onde vêm as palavras sorteadas">
        <i class="bi bi-info-circle" aria-hidden="true"></i>
      </button>

      @if (infoOpen()) {
        <div
          class="cv-info-popover"
          role="dialog"
          aria-label="Origem das palavras sorteadas"
          (click)="$event.stopPropagation()">
          <div class="cv-info-header">
            <span class="cv-info-title">
              <i class="bi bi-sliders2" aria-hidden="true"></i>
              Palavras do "Sortear área CV"
            </span>
            <button
              type="button"
              class="cv-info-close"
              (click)="closeInfo()"
              aria-label="Fechar explicação">
              &times;
            </button>
          </div>

          <p class="cv-info-text">
            As palavras sorteadas vêm do campo
            <strong>Palavras-chave do currículo para busca e sorteio</strong> em
            <strong>Meu perfil</strong>.
          </p>
          <p class="cv-info-text muted">
            A IA extrai essa lista do seu currículo em PDF, e você pode adicionar,
            editar ou remover qualquer termo lá quando quiser.
          </p>

          <div class="cv-info-meta">
            @if (source === 'profile' && areasCount > 0) {
              <span class="cv-info-pill configured">
                {{ areasCount }} palavra(s) configurada(s) no Meu perfil
              </span>
            } @else if (areasCount > 0) {
              <span class="cv-info-pill fallback">
                Usando fallback automático ({{ areasCount }}) — personalize em Meu perfil
              </span>
            } @else {
              <span class="cv-info-pill fallback">
                Nenhuma palavra cadastrada ainda no Meu perfil
              </span>
            }
          </div>

          <button
            type="button"
            class="cv-info-link-btn"
            (click)="goToProfile()">
            <i class="bi bi-pencil-square" aria-hidden="true"></i>
            Editar palavras no Meu perfil
          </button>
        </div>
      }
    </div>
  `,
  styles: [`
    :host {
      display: inline-flex;
      align-items: center;
    }

    .cv-random-group {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .btn-random-cv {
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--vc-blue, #38bdf8);
      border-radius: 6px;
      padding: 0.35rem 0.7rem;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.2s;
      white-space: nowrap;
    }

    .btn-random-cv:hover:not(:disabled) {
      background: rgba(56, 189, 248, 0.22);
    }

    .btn-random-cv:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    .btn-random-info {
      width: 28px;
      height: 28px;
      border-radius: 6px;
      border: 1px solid rgba(148, 163, 184, 0.28);
      background: rgba(148, 163, 184, 0.08);
      color: var(--vc-muted, #94a3b8);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.86rem;
      cursor: pointer;
      transition: all 0.18s ease;
      flex-shrink: 0;
    }

    .btn-random-info:hover,
    .btn-random-info.active {
      color: var(--vc-blue, #38bdf8);
      border-color: rgba(56, 189, 248, 0.45);
      background: rgba(56, 189, 248, 0.14);
    }

    .cv-info-popover {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      width: min(330px, calc(100vw - 2rem));
      background: var(--vc-panel, #111a33);
      border: 1px solid var(--vc-border, rgba(148, 163, 184, 0.22));
      border-radius: 10px;
      padding: 0.85rem 0.95rem;
      box-shadow: 0 12px 28px rgba(2, 6, 23, 0.52);
      z-index: 60;
      text-align: left;
      color: var(--vc-text, #e2e8f0);
    }

    .cv-info-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 0.5rem;
    }

    .cv-info-title {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--vc-blue, #38bdf8);
    }

    .cv-info-close {
      background: transparent;
      border: none;
      color: var(--vc-muted, #94a3b8);
      font-size: 1.2rem;
      line-height: 1;
      cursor: pointer;
      padding: 0 2px;
    }

    .cv-info-close:hover {
      color: var(--vc-text, #e2e8f0);
    }

    .cv-info-text {
      margin: 0 0 0.45rem;
      font-size: 0.81rem;
      line-height: 1.45;
      color: var(--vc-text, #e2e8f0);
    }

    .cv-info-text.muted {
      color: var(--vc-muted, #94a3b8);
    }

    .cv-info-meta {
      margin: 0.55rem 0 0.65rem;
    }

    .cv-info-pill {
      display: inline-block;
      font-size: 0.74rem;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 999px;
    }

    .cv-info-pill.configured {
      background: rgba(34, 197, 94, 0.14);
      border: 1px solid rgba(34, 197, 94, 0.35);
      color: var(--vc-green, #22c55e);
    }

    .cv-info-pill.fallback {
      background: rgba(234, 179, 8, 0.12);
      border: 1px solid rgba(234, 179, 8, 0.35);
      color: var(--vc-yellow, #eab308);
    }

    .cv-info-link-btn {
      width: 100%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 0.48rem 0.75rem;
      border-radius: 7px;
      border: 1px solid rgba(56, 189, 248, 0.35);
      background: rgba(56, 189, 248, 0.14);
      color: var(--vc-blue, #38bdf8);
      font-size: 0.81rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.18s ease;
    }

    .cv-info-link-btn:hover {
      background: rgba(56, 189, 248, 0.24);
    }

    :host-context([data-theme="light"]) .cv-info-popover {
      background: #ffffff;
      border-color: rgba(15, 23, 42, 0.14);
      box-shadow: 0 12px 26px rgba(15, 23, 42, 0.14);
    }

    :host-context([data-theme="light"]) .btn-random-info {
      background: rgba(15, 23, 42, 0.04);
      border-color: rgba(15, 23, 42, 0.16);
      color: #475569;
    }

    :host-context([data-theme="light"]) .btn-random-info:hover,
    :host-context([data-theme="light"]) .btn-random-info.active {
      color: #0284c7;
      border-color: rgba(2, 132, 199, 0.45);
      background: rgba(2, 132, 199, 0.1);
    }

    :host-context([data-theme="light"]) .cv-info-pill.configured {
      color: #15803d;
      background: rgba(22, 163, 74, 0.1);
      border-color: rgba(22, 163, 74, 0.3);
    }

    :host-context([data-theme="light"]) .cv-info-pill.fallback {
      color: #a16207;
      background: rgba(202, 138, 4, 0.1);
      border-color: rgba(202, 138, 4, 0.3);
    }

    :host-context([data-theme="light"]) .cv-info-link-btn {
      color: #0369a1;
      border-color: rgba(2, 132, 199, 0.35);
      background: rgba(2, 132, 199, 0.09);
    }

    :host-context([data-theme="light"]) .cv-info-link-btn:hover {
      background: rgba(2, 132, 199, 0.16);
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CvRandomControlComponent {
  private readonly router = inject(Router, { optional: true });

  @Input() areasCount = 0;
  @Input() source: CvAreasSource = 'fallback';
  @Input() disabled = false;

  @Output() pickRandom = new EventEmitter<void>();

  readonly infoOpen = signal<boolean>(false);

  @HostListener('document:click')
  onDocumentClick(): void {
    if (this.infoOpen()) {
      this.infoOpen.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.infoOpen()) {
      this.infoOpen.set(false);
    }
  }

  onPickClick(event: MouseEvent): void {
    event.stopPropagation();
    this.infoOpen.set(false);
    this.pickRandom.emit();
  }

  toggleInfo(event: MouseEvent): void {
    event.stopPropagation();
    this.infoOpen.update((v) => !v);
  }

  closeInfo(): void {
    this.infoOpen.set(false);
  }

  goToProfile(): void {
    this.infoOpen.set(false);
    this.router?.navigate(['/meu-perfil'], {
      queryParams: { foco: 'palavras_chave_sorteio' },
    });
  }
}
