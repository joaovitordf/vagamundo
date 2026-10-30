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
    const label = step === 'avaliar' ? 'Avaliação rápida' : (step === 'curriculo' ? 'Currículo em PDF' : 'Carta de Apresentação');
    this.actionStatus.set(`A IA está gerando ${label} para "${job.title || 'a vaga'}"… Aguarde.`);
    this.api.triggerClaude({ url: job.url, step }).subscribe({
      next: () => {
        this.actionStatus.set('');
        this.loadSaved();
      },
      error: (err) => {
        this.actionStatus.set('');
        alert('Erro ao processar com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  markApplied(job: any): void {
    this.actionStatus.set(`Registrando candidatura para "${job.title || 'vaga'}"…`);
    this.api.markApplied({
      url: job.url,
      company: job.company,
      role: job.title || job.role,
      portal: job.portal,
    }).subscribe({
      next: () => {
        this.actionStatus.set('');
        this.loadSaved();
      },
      error: (err) => {
        this.actionStatus.set('');
        alert('Erro ao registrar candidatura: ' + (err.error?.detail || err.message));
      }
    });
  }

  discardJob(job: any): void {
    this.api.discardJob(job.url).subscribe({
      next: () => this.loadSaved(),
      error: (err) => alert('Erro ao descartar: ' + (err.error?.detail || err.message))
    });
  }
}
