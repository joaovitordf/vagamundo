import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
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
  'github-vagas': 'GitHub Vagas BR',
  'remotive-search': 'Remotive',
  'remoteok-search': 'RemoteOK',
  'hn-search': 'Hacker News',
  'linkedin_post': 'LinkedIn (Post)',
};

@Component({
  selector: 'app-descartadas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './descartadas.component.html',
  styleUrl: './descartadas.component.css'
})
export class DescartadasComponent implements OnInit {
  private readonly api = inject(ApiService);

  allDiscarded = signal<any[]>([]);
  filteredJobs = signal<any[]>([]);
  filterText = '';
  loading = signal<boolean>(true);

  ngOnInit(): void {
    this.loadDiscarded();
  }

  loadDiscarded(): void {
    this.loading.set(true);
    this.api.getDiscarded().subscribe({
      next: (jobs) => {
        this.allDiscarded.set(jobs || []);
        this.onFilterChange();
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar descartadas:', err);
        this.loading.set(false);
      }
    });
  }

  onFilterChange(): void {
    const q = this.filterText.toLowerCase().trim();
    if (!q) {
      this.filteredJobs.set(this.allDiscarded());
      return;
    }
    this.filteredJobs.set(
      this.allDiscarded().filter(j =>
        (j.title || '').toLowerCase().includes(q) ||
        (j.company || '').toLowerCase().includes(q)
      )
    );
  }

  getPortalName(portal?: string): string {
    return portal ? (PORTAIS[portal] || portal.replace(/-search$/, '')) : 'Portal';
  }

  restoreJob(job: any): void {
    this.api.restoreJob(job.url).subscribe({
      next: () => {
        this.loadDiscarded();
      },
      error: (err) => alert('Erro ao restaurar vaga: ' + err.message)
    });
  }

  clearDiscarded(): void {
    if (!this.allDiscarded().length) return;
    const ok = confirm(`Tem certeza que deseja limpar permanentemente ${this.allDiscarded().length} vagas descartadas da memória do sistema?`);
    if (!ok) return;

    this.loading.set(true);
    this.api.clearDiscarded().subscribe({
      next: () => {
        this.loadDiscarded();
      },
      error: (err) => {
        this.loading.set(false);
        alert('Erro ao limpar vagas descartadas: ' + (err.error?.detail || err.message));
      }
    });
  }
}
