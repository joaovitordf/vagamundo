import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { ToastService } from '../../core/services/toast.service';
import { ProfileResponse } from '../../core/models/vaga.model';

const NOMES: Record<string, string> = {
  estagio: 'estágio',
  junior: 'júnior',
  pleno: 'pleno',
  senior: 'sênior',
  especialista: 'especialista',
  staff: 'staff',
  lead: 'lead',
  gestao: 'gestão',
  remoto: 'remoto',
  hibrido: 'híbrido',
  presencial: 'presencial',
  temporario: 'temporário'
};

@Component({
  selector: 'app-meu-perfil',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meu-perfil.component.html',
  styleUrl: './meu-perfil.component.css'
})
export class MeuPerfilComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);

  profileData = signal<ProfileResponse | null>(null);
  schema = signal<Array<{ title: string; fields: any[] }>>([]);
  uploadStatus = signal<string>('');
  saveStatus = signal<string>('');
  saving = signal<boolean>(false);
  confirmedPrivacy = false;

  aiStatus = signal<string>('');
  isAiRunning = signal<boolean>(false);
  dismissedWarning = signal<boolean>(false);

  // Armazena diretamente os valores dos campos com suporte a two-way data-binding limpo
  formValues: Record<string, any> = {};

  private currentUploadKind: 'cv' | 'linkedin' = 'cv';

  ngOnInit(): void {
    this.loadProfile();
  }

  loadProfile(refresh = false): void {
    this.api.getProfile(refresh).subscribe({
      next: (res) => {
        this.profileData.set(res);
        this.schema.set(res.schema || []);

        const newVals: Record<string, any> = {};
        const ans = res.answers || {};

        for (const sec of res.schema || []) {
          for (const field of sec.fields) {
            const raw = ans[field.key];
            if (field.type === 'lines') {
              newVals[field.key] = Array.isArray(raw) ? raw.join('\n') : (raw || '');
            } else if (field.type === 'multi') {
              newVals[field.key] = Array.isArray(raw) ? [...raw] : [];
            } else {
              newVals[field.key] = raw ?? '';
            }
          }
        }
        this.formValues = newVals;
      },
      error: (err) => console.error('Erro ao carregar perfil:', err)
    });
  }

  get privacyInfo(): { type: 'ok' | 'warn'; message: string } | null {
    if (this.dismissedWarning()) return null;
    const p = this.profileData()?.privacy;
    if (!p) return null;
    const repo = p.repo ? ` (${p.repo})` : '';
    const status = p.status;
    if (status === 'privado') {
      return { type: 'ok', message: `Seu repositório no GitHub${repo} é privado: o perfil fica visível só para você.` };
    }
    if (status === 'local') {
      return { type: 'ok', message: 'Este projeto não está ligado a nenhum repositório on-line: o perfil fica só no seu computador.' };
    }
    if (status === 'outro') {
      return { type: 'warn', message: '[Aviso] Este projeto está ligado a um repositório fora do GitHub. Confira se ele é privado antes de enviar (push) o seu perfil.' };
    }
    if (status === 'publico') {
      return { type: 'warn', message: `[Aviso] Atenção: seu repositório${repo} é PÚBLICO. O perfil (nome, contatos, histórico, pretensão) vai para arquivos que o git publica. Não faça push dele, ou passe a usar um repositório privado (seção 8 do SETUP.md).` };
    }
    return null;
  }

  dismissWarning(): void {
    this.dismissedWarning.set(true);
  }

  showConfirmBox(): boolean {
    const status = this.profileData()?.privacy?.status;
    return status === 'publico';
  }

  allUploadedFiles(): Array<{ kind: 'cv' | 'linkedin'; kindLabel: string; name: string; size: number }> {
    const p = this.profileData();
    if (!p || !p.files) return [];
    const list: Array<{ kind: 'cv' | 'linkedin'; kindLabel: string; name: string; size: number }> = [];
    (p.files.cv || []).forEach(f => list.push({ kind: 'cv', kindLabel: 'Currículo', name: f.name, size: f.size }));
    (p.files.linkedin || []).forEach(f => list.push({ kind: 'linkedin', kindLabel: 'LinkedIn', name: f.name, size: f.size }));
    return list;
  }

  formatKb(bytes: number): number {
    return Math.max(1, Math.round(bytes / 1024));
  }

  triggerUpload(kind: 'cv' | 'linkedin'): void {
    this.currentUploadKind = kind;
    const input = document.getElementById('upload-input') as HTMLInputElement | null;
    if (input) input.click();
  }

  onFileSelected(event: any): void {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    if (file.size > 10 * 1024 * 1024) {
      this.uploadStatus.set('Arquivo grande demais (máximo 10 MB).');
      return;
    }

    this.uploadStatus.set('Enviando…');
    const reader = new FileReader();
    reader.onload = () => {
      const base64Data = String(reader.result).split(',', 2)[1] || '';
      this.api.uploadFile(this.currentUploadKind, file.name, base64Data).subscribe({
        next: (res) => {
          this.uploadStatus.set(`Recebido: ${res.saved}.`);
          this.loadProfile(true);
        },
        error: (err) => this.uploadStatus.set('Não consegui guardar: ' + err.message)
      });
    };
    reader.readAsDataURL(file);
  }

  removeFile(kind: string, name: string): void {
    if (!confirm(`Remover ${name}?`)) return;
    this.api.removeUpload(kind, name).subscribe({
      next: () => {
        this.toast.success(`Arquivo "${name}" removido.`);
        this.loadProfile(true);
      },
      error: (err) => this.toast.error('Erro ao remover arquivo: ' + (err?.error?.detail || err.message))
    });
  }

  isMultiChecked(key: string, opt: string): boolean {
    const arr = this.formValues[key];
    return Array.isArray(arr) && arr.includes(opt);
  }

  onMultiChange(key: string, opt: string, event: any): void {
    const checked = event.target.checked;
    const cur: string[] = Array.isArray(this.formValues[key]) ? [...this.formValues[key]] : [];
    if (checked && !cur.includes(opt)) {
      cur.push(opt);
    } else if (!checked) {
      const idx = cur.indexOf(opt);
      if (idx !== -1) cur.splice(idx, 1);
    }
    this.formValues[key] = cur;
  }

  getOptionName(opt: string): string {
    return NOMES[opt] || opt;
  }

  saveAnswers(): void {
    this.saving.set(true);
    this.saveStatus.set('Salvando…');
    this.api.saveProfileAnswers(this.formValues).subscribe({
      next: (res) => {
        const ans = res.answers || {};
        for (const sec of this.schema()) {
          for (const field of sec.fields) {
            const raw = ans[field.key];
            if (field.type === 'lines') {
              this.formValues[field.key] = Array.isArray(raw) ? raw.join('\n') : (raw || '');
            } else if (field.type === 'multi') {
              this.formValues[field.key] = Array.isArray(raw) ? [...raw] : [];
            } else {
              this.formValues[field.key] = raw ?? '';
            }
          }
        }
        this.saveStatus.set('Respostas salvas.');
        this.saving.set(false);
      },
      error: (err) => {
        this.saveStatus.set('Não consegui salvar: ' + err.message);
        this.saving.set(false);
      }
    });
  }

  isAiDisabled(): boolean {
    if (this.isAiRunning()) return true;
    if (this.allUploadedFiles().length === 0) return true;
    if (this.showConfirmBox() && !this.confirmedPrivacy) return true;
    return false;
  }

  updateButtonState(): void {
    // triggers change detection
  }

  isProfileReady(): boolean {
    return Boolean(this.profileData()?.ready);
  }

  profileReport(): string {
    return this.profileData()?.report || '';
  }

  profileText(): string {
    return this.profileData()?.profile || '';
  }

  cleanProfileText(text: string): string {
    return text.replace(/^---[\s\S]*?---\s*/, '');
  }

  generateProfileWithAi(): void {
    this.isAiRunning.set(true);
    this.aiStatus.set('Salvando respostas antes de acionar a IA…');

    this.api.saveProfileAnswers(this.formValues).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: () => {
        this.aiStatus.set('A IA está montando o seu perfil… isso pode levar alguns instantes.');
        this.api.triggerClaude({ step: 'perfil', confirm: this.confirmedPrivacy }).pipe(
          takeUntilDestroyed(this.destroyRef)
        ).subscribe({
          next: () => {
            this.isAiRunning.set(false);
            this.aiStatus.set('Perfil montado com sucesso!');
            this.loadProfile(true);
          },
          error: (err) => {
            this.isAiRunning.set(false);
            const detail = err?.error?.detail || err?.message || 'falha inesperada';
            this.aiStatus.set('Não consegui concluir com a IA: ' + detail);
          }
        });
      },
      error: (err) => {
        this.isAiRunning.set(false);
        this.aiStatus.set('Não consegui salvar: ' + (err?.error?.detail || err?.message || 'falha inesperada'));
      }
    });
  }
}
