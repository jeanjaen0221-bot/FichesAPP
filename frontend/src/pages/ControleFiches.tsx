import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { EnTete, Erreur, useCharger } from '../composants/ui'

// Contrôle des fiches à venir : ce qui est à corriger ou à vérifier avant le service.
// Le serveur relit chaque fiche (site ou ChatGPT) avec les règles ; rien n'est modifié.

type Probleme = { niveau: 'a_corriger' | 'a_verifier'; message: string }
type FicheControlee = {
  id: string; date: string; heure: string; client: string; couverts: number; statut: string; statut_libelle: string
  problemes: Probleme[]
}
type Resultat = { controlees: number; jours: number; fiches: FicheControlee[] }

const PERIODES = [{ jours: 7, libelle: '7 jours' }, { jours: 30, libelle: '30 jours' }, { jours: 60, libelle: '60 jours' }, { jours: 365, libelle: '1 an' }]
const dateCourte = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('fr-BE', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' })

export default function ControleFiches() {
  const [jours, setJours] = useState(60)
  const [seulementACorriger, setSeulementACorriger] = useState(false)
  const { donnees, erreur } = useCharger(() => api.get<Resultat>(`/api/fiches/controle?jours=${jours}`), [jours])

  const fiches = (donnees?.fiches ?? [])
    .map((f) => ({ ...f, problemes: f.problemes.filter((p) => !seulementACorriger || p.niveau === 'a_corriger') }))
    .filter((f) => f.problemes.length > 0)
  const nbCorriger = (donnees?.fiches ?? []).filter((f) => f.problemes.some((p) => p.niveau === 'a_corriger')).length

  return (
    <>
      <EnTete titre="Contrôle des fiches" sousTitre="Les fiches à venir relues avec les règles de l'outil et les consignes de ChatGPT. Rien n'est modifié : ouvrir la fiche pour corriger." />
      <Erreur message={erreur} />
      <div className="filtres">
        <div className="onglets">
          {PERIODES.map((p) => <button key={p.jours} className={jours === p.jours ? 'actif' : ''} onClick={() => setJours(p.jours)}>{p.libelle}</button>)}
        </div>
        <label className="case">
          <input type="checkbox" style={{ minWidth: 0 }} checked={seulementACorriger} onChange={(e) => setSeulementACorriger(e.target.checked)} />
          {' '}Seulement ce qui est à corriger
        </label>
      </div>
      {donnees && (
        <div className={`bandeau ${nbCorriger ? 'attention' : 'info'}`}>
          {donnees.controlees} fiche(s) à venir contrôlée(s) sur {donnees.jours} jours : {nbCorriger} à corriger,
          {' '}{donnees.fiches.length - nbCorriger} avec seulement des points à vérifier,
          {' '}{donnees.controlees - donnees.fiches.length} sans remarque.
        </div>
      )}
      {fiches.map((f) => (
        <section className="carte" key={f.id}>
          <h2>
            <Link to={`/fiches/${f.id}`}>{f.client}</Link>
            {' '}<span className="muet">— {dateCourte(f.date)} {f.heure} · {f.couverts} couverts · {f.statut_libelle}</span>
          </h2>
          <ul>
            {f.problemes.map((p, i) => (
              <li key={i}>
                <span className={`pastille ${p.niveau === 'a_corriger' ? 'rouge' : 'ambre'}`}>{p.niveau === 'a_corriger' ? 'À corriger' : 'À vérifier'}</span>
                {' '}{p.message}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {donnees && fiches.length === 0 && <p className="muet">Rien à signaler.</p>}
    </>
  )
}
