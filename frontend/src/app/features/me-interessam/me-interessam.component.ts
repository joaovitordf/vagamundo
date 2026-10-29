import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../core/services/api.service';

const PORTAIS: Record<string, string> = {
  'gupy-search': 'Gupy',
  'solides-search': 'Sólides',
  'vagas-search': 'VAGAS.com',
  'infojobs-search': 'InfoJobs',
  'remotar-search': 'Remotar',
  'greenhouse-search': 'Greenhouse',
  'programathor-search': 'Programathor',
  'geekhunter-search': 'GeekHunter',
  'michaelpage-search': 'Michael Page',
  'roberthalf-search': 'Robert Half',
  'trampos-search': 'Trampos',
  'pcd-search': 'PCD Online',
  'agrobase-search': 'Agrobase',
  'agrosearch-search': 'AGROSearch',
  'digai-search': 'DigAÍ',
  'empregos-search': 'Empregos.com.br',
  'linkedin-search': 'LinkedIn',
  'freehire-search': 'freehire',
  'hh-search': 'HeadHunter (hh.ru)',
  'habrcareer-search': 'Habr Career',
  'google-careers': 'Google Careers',
  'eures': 'EURES (Europa)',
};

@Component({
  selector: 'app-me-interessam',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './me-interessam.component.html',
  styleUrl: './me-interessam.component.css'
})
export class MeInteressamComponent implements OnInit {
  private readonly api = inject(ApiService);

  savedJobs = signal<any[]>([]);
  loading = signal<boolean>(true);
  actionStatus = signal<string>('');

  ngOnInit(): void {
    this.loadSaved();
  }

  loadSaved(): void {
    this.loading.set(true);
    this.api.getSaved().subscribe({
      next: (jobs) => {
        this.savedJobs.set(jobs || []);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar vagas salvas:', err);
        this.loading.set(false);
      }
    });
  }

  getPortalName(portal?: string): string {
    return portal ? (PORTAIS[portal] || portal.replace(/-search$/, '')) : 'Portal';
  }

  encodePath(path: string): string {
    return encodeURIComponent(path || '');
  }

  runAi(job: any, step: string): void {
    this.actionStatus.set(`A IA está processando (${step}) para ${job.title}…`);
    this.api.triggerClaude({ url: job.url, step }).subscribe({
      next: () => {
        this.pollAiStatus();
      },
      error: (err) => {
        this.actionStatus.set('');
        alert('Erro ao acionar IA: ' + err.message);
      }
    });
  }

  private pollAiStatus(): void {
    const interval = setInterval(() => {
      this.api.getSearchStatus().subscribe({
        next: (st) => {
          const agent = st.agent || st.claude;
          if (agent && agent.running) {
            this.actionStatus.set(`Processando desde ${agent.started?.slice(11, 16) || ''}…`);
          } else {
            clearInterval(interval);
            this.actionStatus.set('');
            this.loadSaved();
          }
        },
        error: () => {
          clearInterval(interval);
          this.actionStatus.set('');
        }
      });
    }, 2500);
  }

  markApplied(job: any): void {
    this.api.markDecision([job.url], 'interesse', { ...job, applied: true }).subscribe({
      next: () => {
        alert('Vaga registrada! Acesse a aba Candidaturas para detalhes.');
        this.loadSaved();
      },
      error: (err) => alert('Erro: ' + err.message)
    });
  }

  discardJob(job: any): void {
    this.api.discardJob(job.url).subscribe({
      next: () => this.loadSaved(),
      error: (err) => alert('Erro ao descartar: ' + err.message)
    });
  }
}
