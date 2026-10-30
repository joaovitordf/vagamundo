import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../core/services/api.service';

const STATUS_LABELS: Record<string, string> = {
  applied: 'Enviada',
  screening: 'Triagem',
  interview: 'Entrevista',
  offer: 'Proposta',
  rejected: 'Rejeitada',
  withdrawn: 'Desistência'
};

@Component({
  selector: 'app-candidaturas',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './candidaturas.component.html',
  styleUrl: './candidaturas.component.css'
})
export class CandidaturasComponent implements OnInit {
  private readonly api = inject(ApiService);
  applications = signal<any[]>([]);
  loading = signal<boolean>(true);

  ngOnInit(): void {
    this.loadApplications();
  }

  loadApplications(): void {
    this.loading.set(true);
    this.api.getApplications().subscribe({
      next: (apps) => {
        this.applications.set(apps || []);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar candidaturas:', err);
        this.loading.set(false);
      }
    });
  }

  formatDate(d: string): string {
    if (!d) return '-';
    const parts = d.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return d;
  }

  getStatusLabel(s: string): string {
    return STATUS_LABELS[(s || '').toLowerCase()] || s || 'Enviada';
  }

  encodePath(path: string): string {
    return encodeURIComponent(path || '');
  }
}
