import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { ApplicationTimelineEvent } from '../../core/models/vaga.model';

const STATUS_LABELS: Record<string, string> = {
  applied: 'Enviada',
  screening: 'Triagem',
  interview: 'Entrevista',
  offer: 'Proposta',
  hired: 'Contratação',
  rejected: 'Não seguiu',
  no_response: 'Sem resposta',
  offer_declined: 'Proposta recusada',
  withdrawn: 'Desistência'
};

@Component({
  selector: 'app-candidaturas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './candidaturas.component.html',
  styleUrl: './candidaturas.component.css'
})
export class CandidaturasComponent implements OnInit {
  private readonly api = inject(ApiService);
  applications = signal<any[]>([]);
  loading = signal<boolean>(true);

  // Modal de Histórico de Entrevistas
  selectedApp = signal<any | null>(null);
  historyEvents = signal<ApplicationTimelineEvent[]>([]);
  loadingEvents = signal<boolean>(false);
  savingEvent = signal<boolean>(false);
  preparingInterview = signal<string | null>(null);
  generatingDoc = signal<string | null>(null);

  // Campos do formulário de novo evento
  formStage = 'Triagem RH';
  formDate = new Date().toISOString().substring(0, 10);
  formFeedback = '';
  formQuestions = '';
  formStatus = 'interview';

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

  prepareInterview(app: any): void {
    const url = app?.url || app?.job_url || app?.source;
    if (!url) {
      alert('URL da vaga não disponível para preparar entrevista.');
      return;
    }
    this.preparingInterview.set(url);
    this.api.triggerClaude({ url, step: 'entrevista' }).subscribe({
      next: () => {
        this.preparingInterview.set(null);
        this.loadApplications();
        if (this.selectedApp()) {
          // Refresh selected app pdf_entrevista
          this.api.getApplications().subscribe({
            next: (apps) => {
              const updated = apps.find(a => (a.url || a.job_url || a.source) === url);
              if (updated) this.selectedApp.set(updated);
            }
          });
        }
      },
      error: (err) => {
        this.preparingInterview.set(null);
        alert('Erro ao preparar entrevista com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  generateCarta(app: any): void {
    const url = app?.url || app?.job_url || app?.source;
    if (!url) {
      alert('URL da vaga não disponível para gerar carta de apresentação.');
      return;
    }
    const key = url + '_carta';
    this.generatingDoc.set(key);
    this.api.triggerClaude({ url, step: 'carta' }).subscribe({
      next: () => {
        this.generatingDoc.set(null);
        this.loadApplications();
        if (this.selectedApp()) {
          this.api.getApplications().subscribe({
            next: (apps) => {
              const updated = apps.find(a => (a.url || a.job_url || a.source) === url);
              if (updated) this.selectedApp.set(updated);
            }
          });
        }
      },
      error: (err) => {
        this.generatingDoc.set(null);
        alert('Erro ao gerar carta com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  generateCv(app: any): void {
    const url = app?.url || app?.job_url || app?.source;
    if (!url) {
      alert('URL da vaga não disponível para gerar currículo.');
      return;
    }
    const key = url + '_cv';
    this.generatingDoc.set(key);
    this.api.triggerClaude({ url, step: 'curriculo' }).subscribe({
      next: () => {
        this.generatingDoc.set(null);
        this.loadApplications();
        if (this.selectedApp()) {
          this.api.getApplications().subscribe({
            next: (apps) => {
              const updated = apps.find(a => (a.url || a.job_url || a.source) === url);
              if (updated) this.selectedApp.set(updated);
            }
          });
        }
      },
      error: (err) => {
        this.generatingDoc.set(null);
        alert('Erro ao gerar currículo com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  deleteApplication(app: any): void {
    const title = app.role || app.title || app.job_title || 'esta vaga';
    const company = app.company || app.job_company || '';
    const desc = company ? `"${title}" na empresa "${company}"` : `"${title}"`;
    if (!confirm(`Deseja realmente remover a candidatura para ${desc} da sua lista?`)) {
      return;
    }
    const url = app.url || app.source || app.job_url || '';
    const id = app.id;
    const jobId = app.job_id;
    this.api.removeApplication({ url, id, job_id: jobId }).subscribe({
      next: () => {
        this.loadApplications();
      },
      error: (err) => {
        alert('Erro ao remover candidatura: ' + (err.error?.detail || err.message));
      }
    });
  }

  // --- Modal de Histórico de Entrevistas ---
  openHistoryModal(app: any): void {
    this.selectedApp.set(app);
    this.formStage = 'Triagem RH';
    this.formDate = new Date().toISOString().substring(0, 10);
    this.formFeedback = '';
    this.formQuestions = '';
    this.formStatus = app.status || 'interview';
    this.loadEventsForSelected();
  }

  closeHistoryModal(): void {
    this.selectedApp.set(null);
    this.historyEvents.set([]);
  }

  loadEventsForSelected(): void {
    const app = this.selectedApp();
    if (!app || !app.id) {
      this.historyEvents.set([]);
      return;
    }
    this.loadingEvents.set(true);
    this.api.getApplicationEvents(app.id).subscribe({
      next: (res) => {
        this.historyEvents.set(res?.events || []);
        this.loadingEvents.set(false);
      },
      error: (err) => {
        console.error('Erro ao buscar histórico:', err);
        this.loadingEvents.set(false);
      }
    });
  }

  submitNewEvent(): void {
    const app = this.selectedApp();
    if (!app) return;

    if (!this.formStage.trim()) {
      alert('Informe a etapa do processo seletivo.');
      return;
    }

    this.savingEvent.set(true);
    const payload = {
      application_id: app.id,
      job_id: app.job_id,
      url: app.url || app.job_url || app.source,
      stage: this.formStage.trim(),
      event_date: this.formDate,
      feedback: this.formFeedback.trim(),
      questions_and_answers: this.formQuestions.trim(),
      status: this.formStatus
    };

    this.api.addApplicationEvent(payload).subscribe({
      next: () => {
        this.savingEvent.set(false);
        this.formFeedback = '';
        this.formQuestions = '';
        this.loadEventsForSelected();
        this.loadApplications();
      },
      error: (err) => {
        this.savingEvent.set(false);
        alert('Erro ao registrar etapa: ' + (err.error?.detail || err.message));
      }
    });
  }

  deleteEvent(eventId?: number): void {
    if (!eventId) return;
    if (!confirm('Deseja excluir este registro de histórico?')) return;

    this.api.deleteApplicationEvent(eventId).subscribe({
      next: () => {
        this.loadEventsForSelected();
        this.loadApplications();
      },
      error: (err) => {
        alert('Erro ao excluir evento: ' + (err.error?.detail || err.message));
      }
    });
  }
}
