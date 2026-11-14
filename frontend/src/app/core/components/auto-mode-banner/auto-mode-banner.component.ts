import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { AutoModeService } from '../../services/auto-mode.service';
import { ToastService } from '../../services/toast.service';

@Component({
  selector: 'app-auto-mode-banner',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './auto-mode-banner.component.html',
  styleUrl: './auto-mode-banner.component.css',
})
export class AutoModeBannerComponent {
  readonly auto = inject(AutoModeService);
  private readonly toast = inject(ToastService);

  phaseLabel(): string {
    const st = this.auto.status();
    if (!st) return '';
    const isRecruiters = st.mode === 'recruiters';
    switch (st.phase) {
      case 'picking_keywords':
        return 'IA sorteando até 2 palavras-chave do seu currículo…';
      case 'searching': {
        if (isRecruiters) {
          return 'Sincronizando publicações de recrutadores…';
        }
        const pct = Math.round(st.search_progress?.percent || 0);
        return `Buscando vagas (últimos ${st.jobage}d)… ${pct}%`;
      }
      case 'screening': {
        const cur = st.batch_progress?.current ?? st.round_screened ?? st.counts.screened ?? 0;
        const tot = st.batch_progress?.total ?? st.round_eligible_count ?? st.counts.to_screen ?? 0;
        const title = st.batch_progress?.current_title ? ` — ${st.batch_progress.current_title}` : '';
        return `${isRecruiters ? 'Triando publicação' : 'Triando vaga'} ${cur} de ${tot}${title}`;
      }
      case 'cooldown': {
        const nextRound = (st.round || 1) + 1;
        const label = this.auto.cooldownCountdownLabel();
        return isRecruiters
          ? `Intervalo anti-ban — Próxima rodada de recrutadores (#${nextRound}) em ${label}`
          : `Intervalo anti-ban — Próxima rodada (#${nextRound}) em ${label}`;
      }
      case 'done':
        return isRecruiters ? 'Rodada automática de recrutadores concluída' : 'Rodada automática concluída';
      case 'cancelled':
        return 'Modo Automático interrompido';
      case 'error':
        return 'Modo Automático parou com erro';
      default:
        return '';
    }
  }

  onUndoRun(): void {
    const runId = this.auto.status()?.run_id || undefined;
    this.auto.undoRun(runId).subscribe({
      next: () => this.toast.success('Rodada automática desfeita com sucesso.'),
      error: (err) => this.toast.error('Erro ao desfazer rodada: ' + (err?.error?.detail || err?.message || 'Falha na requisição')),
    });
  }
}
