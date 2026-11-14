import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { ToastService } from '../../core/services/toast.service';
import { ProviderSettingsItem, SettingsResponse } from '../../core/models/vaga.model';

@Component({
  selector: 'app-configuracoes',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './configuracoes.component.html',
  styleUrl: './configuracoes.component.css'
})
export class ConfiguracoesComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);

  settingsData = signal<SettingsResponse | null>(null);
  chosenProvider = 'auto';
  consentGiven = false;
  saving = signal<boolean>(false);
  statusMsg = signal<string>('');

  providerKeys: Record<string, string> = {};
  providerModels: Record<string, string> = {};
  providerBaseUrls: Record<string, string> = {};
  clearKeyFlags: Record<string, boolean> = {};

  ngOnInit(): void {
    this.loadSettings();
  }

  loadSettings(): void {
    this.api.getSettings().subscribe({
      next: (res) => {
        this.settingsData.set(res);
        this.chosenProvider = res.provider || 'auto';
        this.consentGiven = Boolean(res.consent);
        this.syncFormFromSettings(res);
      },
      error: (err) => {
        console.error('Erro ao carregar configurações:', err);
        this.toast.error('Erro ao carregar configurações de IA.');
      }
    });
  }

  private syncFormFromSettings(res: SettingsResponse): void {
    const nextKeys: Record<string, string> = {};
    const nextModels: Record<string, string> = {};
    const nextBaseUrls: Record<string, string> = {};
    const nextClear: Record<string, boolean> = {};
    for (const item of res.providers || []) {
      nextKeys[item.id] = '';
      nextModels[item.id] = item.model || item.default_model || '';
      nextBaseUrls[item.id] = item.base_url || '';
      nextClear[item.id] = false;
    }
    this.providerKeys = nextKeys;
    this.providerModels = nextModels;
    this.providerBaseUrls = nextBaseUrls;
    this.clearKeyFlags = nextClear;
  }

  activeProviderLabel(): string {
    const s = this.settingsData();
    if (!s) return 'Automático';
    if (s.active?.label) {
      return s.active.available ? s.active.label : `${s.active.label} (indisponível)`;
    }
    const found = (s.providers || []).find(item => item.id === s.provider);
    if (found?.label) return found.label;
    return s.provider === 'auto' ? 'Automático' : (s.provider || 'Automático');
  }

  activeModelLabel(): string {
    const s = this.settingsData();
    return s?.active?.model || s?.model || '';
  }

  hasProviderKey(provider: string): boolean {
    const s = this.settingsData();
    if (!s) return false;
    const item = (s.providers || []).find(p => p.id === provider);
    if (item && typeof item.has_key === 'boolean') {
      return item.has_key;
    }
    return s.provider === provider && Boolean(s.has_key);
  }

  isProviderReady(item: ProviderSettingsItem): boolean {
    return Boolean(item.has_key || item.cli_found);
  }

  isProviderHighlighted(item: ProviderSettingsItem): boolean {
    if (this.chosenProvider === item.id) return true;
    if (this.chosenProvider === 'auto') {
      return this.settingsData()?.active?.provider === item.id;
    }
    return false;
  }

  providerIcon(id: string): string {
    switch (id) {
      case 'gemini': return 'bi-stars';
      case 'openai': return 'bi-robot';
      case 'claude': return 'bi-chat-square-text';
      default: return 'bi-cpu';
    }
  }

  saveSettings(): void {
    this.saving.set(true);
    this.statusMsg.set('Salvando…');

    const providersPayload: Record<string, any> = {};
    for (const item of this.settingsData()?.providers || []) {
      const cfg: Record<string, any> = {};
      const modelVal = (this.providerModels[item.id] || '').trim();
      if (modelVal) {
        cfg['model'] = modelVal;
      }
      const keyVal = (this.providerKeys[item.id] || '').trim();
      if (keyVal) {
        cfg['api_key'] = keyVal;
      } else if (this.clearKeyFlags[item.id]) {
        cfg['clear_key'] = true;
      }
      if (item.supports_base_url) {
        cfg['base_url'] = (this.providerBaseUrls[item.id] || '').trim();
      }
      if (Object.keys(cfg).length > 0) {
        providersPayload[item.id] = cfg;
      }
    }

    const payload: Record<string, any> = {
      provider: this.chosenProvider,
      consent: this.consentGiven,
      providers: providersPayload,
    };

    this.api.saveSettings(payload).subscribe({
      next: (res) => {
        this.saving.set(false);
        this.statusMsg.set('Configurações salvas no .env local com sucesso!');
        this.toast.success('Configurações do assistente de IA salvas.');
        if (res && Array.isArray(res.providers)) {
          this.settingsData.set(res);
          this.chosenProvider = res.provider || 'auto';
          this.consentGiven = Boolean(res.consent);
          this.syncFormFromSettings(res);
        } else {
          this.loadSettings();
        }
      },
      error: (err) => {
        this.saving.set(false);
        const msg = 'Erro ao salvar configurações: ' + (err?.error?.detail || err?.message || 'Falha na requisição');
        this.statusMsg.set(msg);
        this.toast.error(msg);
      }
    });
  }
}
