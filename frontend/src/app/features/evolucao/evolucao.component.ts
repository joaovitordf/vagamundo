import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../core/services/api.service';
import { EvolutionResponse, SourceAuditItem } from '../../core/models/vaga.model';

interface SourceDisplayRow {
  key: string;
  name: string;
  description: string;
  path: string;
  exists: boolean;
  files: number;
  lines: number;
  bytes?: number;
}

@Component({
  selector: 'app-evolucao',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './evolucao.component.html',
  styleUrl: './evolucao.component.css'
})
export class EvolucaoComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private statusTimer: ReturnType<typeof setTimeout> | null = null;

  evolutionData = signal<EvolutionResponse | null>(null);
  updating = signal<boolean>(false);
  statusMsg = signal<string>('');
  errorMsg = signal<string>('');

  readonly sourceLabels: Record<string, { name: string; description: string }> = {
    applications_tracker: { name: 'Rastreador de Candidaturas', description: 'Registro de vagas aplicadas (SQLite / CSV)' },
    candidate_profile: { name: 'Perfil da Pessoa Candidata', description: 'Metadados profissionais (01-candidate-profile.md)' },
    linkedin: { name: 'LinkedIn Profissional', description: 'Perfil salvo em PDF na pasta documents/linkedin' },
    projects: { name: 'Inventário de Projetos', description: 'Projetos e experiências comprovadas' },
    interviews: { name: 'Contexto de Entrevistas', description: 'Perguntas, respostas e feedbacks de processos' },
    application_notes: { name: 'Anotações de Candidatura', description: 'Cartas, versões de CV e notas de aplicação' },
    guidance: { name: 'Regras de Orientação (AGENTS)', description: 'Instruções e guardas de conduta do sistema' },
    usage: { name: 'Manual e Preferências (CLAUDE)', description: 'Diretrizes de operação da busca' }
  };

  ngOnInit(): void {
    this.loadEvolution();
  }

  ngOnDestroy(): void {
    if (this.statusTimer) {
      clearTimeout(this.statusTimer);
      this.statusTimer = null;
    }
  }

  loadEvolution(): void {
    this.api.getEvolution().subscribe({
      next: (data) => {
        this.evolutionData.set(data);
      },
      error: (err) => {
        console.error('Erro ao carregar evolução:', err);
        this.errorMsg.set('Não foi possível carregar os dados de evolução.');
      }
    });
  }

  updateEvolution(): void {
    this.updating.set(true);
    this.statusMsg.set('Auditando fontes, sincronizando candidaturas e recalculando prioridades…');
    this.errorMsg.set('');

    this.api.updateEvolution().subscribe({
      next: (res) => {
        this.updating.set(false);
        this.statusMsg.set('Evolução profissional recalculada e sincronizada com sucesso!');
        if (res && res.evolution) {
          this.evolutionData.set(res.evolution);
        } else {
          this.loadEvolution();
        }
        if (this.statusTimer) {
          clearTimeout(this.statusTimer);
        }
        this.statusTimer = setTimeout(() => {
          this.statusTimer = null;
          this.statusMsg.set('');
        }, 4000);
      },
      error: (err) => {
        this.updating.set(false);
        this.statusMsg.set('');
        this.errorMsg.set('Falha ao atualizar evolução: ' + (err.error?.detail || err.message || 'Erro desconhecido'));
      }
    });
  }

  get metrics() {
    return this.evolutionData()?.evolution?.metrics;
  }

  get summaryText(): string {
    return this.evolutionData()?.evolution?.summary || 'Ainda não há uma atualização da evolução.';
  }

  get priorities(): string[] {
    return this.evolutionData()?.evolution?.priorities || [];
  }

  get gaps(): string[] {
    return this.evolutionData()?.gaps || [];
  }

  get actions(): string[] {
    return this.evolutionData()?.actions || [];
  }

  get projects(): string[] {
    return this.evolutionData()?.projects || [];
  }

  get warnings(): string[] {
    return this.evolutionData()?.validation?.warnings || [];
  }

  get errors(): string[] {
    return this.evolutionData()?.validation?.errors || [];
  }

  get sourceRows(): SourceDisplayRow[] {
    const sources = this.evolutionData()?.validation?.sources;
    if (!sources) return [];

    return Object.entries(sources).map(([key, item]: [string, SourceAuditItem]) => {
      const info = this.sourceLabels[key] || { name: key, description: 'Fonte do sistema' };
      return {
        key,
        name: info.name,
        description: info.description,
        path: item.path,
        exists: item.exists,
        files: item.files || 0,
        lines: item.lines || 0,
        bytes: item.bytes
      };
    });
  }

  formatDate(dateStr?: string | null): string {
    if (!dateStr) return 'Nunca sincronizado';
    try {
      const d = new Date(dateStr);
      return d.toLocaleString('pt-BR');
    } catch {
      return dateStr;
    }
  }
}
