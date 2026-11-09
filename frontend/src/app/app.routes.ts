import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'dashboard',
    pathMatch: 'full'
  },
  {
    path: 'dashboard',
    loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent)
  },
  {
    path: 'buscar-vagas',
    loadComponent: () => import('./features/buscar-vagas/buscar-vagas.component').then(m => m.BuscarVagasComponent)
  },
  {
    path: 'recrutadores',
    loadComponent: () => import('./features/recrutadores/recrutadores.component').then(m => m.RecrutadoresComponent)
  },
  {
    path: 'me-interessam',
    loadComponent: () => import('./features/me-interessam/me-interessam.component').then(m => m.MeInteressamComponent)
  },
  {
    path: 'candidaturas',
    loadComponent: () => import('./features/candidaturas/candidaturas.component').then(m => m.CandidaturasComponent)
  },
  {
    path: 'evolucao',
    loadComponent: () => import('./features/evolucao/evolucao.component').then(m => m.EvolucaoComponent)
  },
  {
    path: 'curriculos-cartas',
    loadComponent: () => import('./features/curriculos-cartas/curriculos-cartas.component').then(m => m.CurriculosCartasComponent)
  },
  {
    path: 'descartadas',
    loadComponent: () => import('./features/descartadas/descartadas.component').then(m => m.DescartadasComponent)
  },
  {
    path: 'meu-perfil',
    loadComponent: () => import('./features/meu-perfil/meu-perfil.component').then(m => m.MeuPerfilComponent)
  },
  {
    path: 'configuracoes',
    loadComponent: () => import('./features/configuracoes/configuracoes.component').then(m => m.ConfiguracoesComponent)
  },
  {
    path: '**',
    redirectTo: 'dashboard'
  }
];
