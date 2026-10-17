import { HOTLINE, formatPhone } from '../data'

export function About() {
  return (
    <main className="page">
      <section className="page-hero">
        <h1 className="display">Technology should adapt to farmers.</h1>
        <p className="lede">
          After a storm or a drought, the last thing a farmer needs is a maze of websites and forms. Willow
          turns all of it into one conversation.
        </p>
      </section>

      <section className="prose">
        <div className="prose-block">
          <h2>What Willow does</h2>
          <p>
            Willow is a voice assistant you reach with a normal phone call. It listens to what happened, asks the
            right follow-up questions, and gathers what your crop insurance claim needs.
          </p>
          <p>
            Then it goes further: it looks for grants, loans and disaster assistance that fit your farm, checks
            each requirement against what you told it, and explains why a program fits or doesn’t.
          </p>
        </div>
        <div className="prose-block">
          <h2>How it works</h2>
          <ol className="flow">
            <li><strong>You call.</strong> Explain your situation naturally. No account, no app needed.</li>
            <li><strong>Willow organizes it.</strong> Your details become a case, with anything missing clearly marked.</li>
            <li><strong>Willow matches you.</strong> Programs are checked rule by rule: what fits, what’s missing, what rules you out.</li>
            <li><strong>You approve.</strong> You get a text with your results. Fix anything, then approve. Nothing is sent without you.</li>
          </ol>
        </div>
        <div className="prose-block">
          <h2>Say it once</h2>
          <p>
            The details you give on one call are reused for every application, so you never answer the same
            question twice.
          </p>
        </div>
        <div className="prose-block">
          <h2>What Willow isn’t</h2>
          <p>
            Willow helps you prepare and file. It doesn’t approve claims or pay benefits; your insurer and the
            agencies running each program make those decisions.
          </p>
        </div>
      </section>

      <section className="cta">
        <div className="cta-card">
          <h2>Try it yourself.</h2>
          <a className="btn btn-leaf cta-btn" href={`tel:${HOTLINE}`}>Call {formatPhone(HOTLINE)}</a>
        </div>
      </section>
    </main>
  )
}
