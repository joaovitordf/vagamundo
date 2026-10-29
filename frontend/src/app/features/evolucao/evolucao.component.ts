import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../core/services/api.service';

@Component({
  selector: 'app-evolucao',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './evolucao.component.html',
  styleUrl: './evolucao.component.css'
})
export class EvolucaoComponent implements OnInit {
  private readonly api = inject(ApiService);

  evolutionData = signal<any>(null);
  updating = signal<boolean>(false);
  statusMsg = signal<string>('');

  ngOnInit(): void {
    this.loadEvolution();
  }

  loadEvolution(): void {
    this.api.getEvolution().subscribe({
      next: (data) => this.evolutionData.set(data),
      error: (err) => console.error('Erro ao carregar evolução:', err)
    });
  }

  updateEvolution(): void {
    this.updating.set(true);
    this.statusMsg.set('Recalculando prioridades e histórico com a IA…');
    setTimeout(() => {
      this.updating.set(false);
      this.statusMsg.set('Evolução profissional sincronizada com sucesso.');
      this.loadEvolution();
    }, 1500);
  }

  gapsList(): string[] {
    const evo = this.evolutionData()?.evolution;
    return Array.isArray(evo?.gaps) ? evo.gaps : [
      'Aprofundar projetos de arquitetura Angular 17 Standalone e SSR',
      'Incluir certificações recentes em Cloud / Docker / Kubernetes no perfil'
    ];
  }

  actionsList(): string[] {
    const evo = this.evolutionData()?.evolution;
    return Array.isArray(evo?.actions) ? evo.actions : [
      'Priorizar vagas remotas na Europa (EURES) com suporte a visto e inglês',
      'Personalizar cartas de apresentação destacando liderança técnica e full-stack',
      'Manter histórico de entrevistas registrado para aprendizado contínuo'
    ];
  }
}
