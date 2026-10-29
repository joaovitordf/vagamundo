import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { SettingsResponse } from '../../core/models/vaga.model';

@Component({
  selector: 'app-configuracoes',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './configuracoes.component.html',
  styleUrl: './configuracoes.component.css'
})
export class ConfiguracoesComponent implements OnInit {
  private readonly api = inject(ApiService);

  settingsData = signal<SettingsResponse | null>(null);
  chosenProvider = 'auto';
  consentGiven = false;
  saving = signal<boolean>(false);
  statusMsg = signal<string>('');

  keys = {
    gemini: '',
    openai: '',
    claude: ''
  };

  ngOnInit(): void {
    this.loadSettings();
  }

  loadSettings(): void {
    this.api.getSettings().subscribe({
      next: (res) => {
        this.settingsData.set(res);
        this.chosenProvider = res.provider || 'auto';
        this.consentGiven = Boolean(res.consent);
      },
      error: (err) => {
        console.error('Erro ao carregar configurações:', err);
      }
    });
  }

  activeProviderLabel(): string {
    const p = this.settingsData()?.provider;
    switch (p) {
      case 'gemini': return 'Google Gemini';
      case 'openai': return 'OpenAI (ChatGPT)';
      case 'claude': return 'Anthropic Claude';
      default: return p || 'Automático';
    }
  }

  hasProviderKey(provider: string): boolean {
    const s = this.settingsData();
    if (!s) return false;
    return s.provider === provider && s.has_key;
  }

  saveSettings(): void {
    this.saving.set(true);
    this.statusMsg.set('Salvando…');

    const payload: any = {
      provider: this.chosenProvider,
      consent: this.consentGiven
    };
    if (this.keys.gemini.trim()) payload.gemini_key = this.keys.gemini.trim();
    if (this.keys.openai.trim()) payload.openai_key = this.keys.openai.trim();
    if (this.keys.claude.trim()) payload.claude_key = this.keys.claude.trim();

    this.api.saveSettings(payload).subscribe({
      next: (res) => {
        this.saving.set(false);
        this.statusMsg.set('Configurações salvas no .env local com sucesso!');
        this.keys = { gemini: '', openai: '', claude: '' };
        this.loadSettings();
      },
      error: (err) => {
        this.saving.set(false);
        this.statusMsg.set('Erro ao salvar configurações: ' + err.message);
      }
    });
  }
}
