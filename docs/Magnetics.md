https://www.reddit.com/r/AskElectronics/comments/1f9d50s/higher_isat_with_stacked_toroids_or_parallel/

https://eedesignpro.com/wp-content/uploads/2023/09/Magnetics_Design.pdf

https://www.mag-inc.com/design/design-guides/inductor-cores-material-and-shape-choices

https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_pwr_ind_app-e.pdf

# Core Loss

* Fundamentals of Power Electronics. Second Edition, p507
    * typical values for exponents
* https://www.ti.com/lit/an/slvaeq9/slvaeq9.pdf#page=5
* https://www.eevblog.com/forum/projects/toroidal-core-for-high-power-buck-converter/msg3085987/#msg3085987
* https://www.ti.com/lit/an/snva038b/snva038b.pdf?ts=1730558298197
    * "The DC Component of the B-Field: This is proportional to the DC component of the inductor current. In fact the
      instantaneous value of B can always be considered proportional to the instantaneous value of the current (for a
      given inductor)."
    * "Peak B-Field: Since B is proportional to I, we can write for the peak B-field:"
    * thermal resistance of inductor, estimated temperature rise
    * Energy Handling Capability of Core:
* https://www.mag-inc.com/Design/Design-Tools/Ferrite-Core-Loss-Calculator
* https://www.coilcraft.com/en-us/tools/power-inductor-finder/#/
* https://www.quora.com/What-is-the-formula-for-calculating-peak-value-of-flux-density-of-an-inductor
  * "B pk= Inductance x peak current divided by (turns x cross sectional area of the core). If you substitute E=Li/t you also get B pk = volts applied x time applied divided by (turns x core cross sectional area). Current is what causes flux so the first equation is the most direct. The second equation is most useful for square wave voltages applied such as in switched mode converters. The same equation applies for sine waves with a multiplying factor (1/4.44) and 1/frequency instead of time applied."


# Resources & Tools
* micrometals
* https://www.e-magnetica.pl/doku.php/start
* https://www.femm.info/wiki/Examples


# Books
* transformer design



DC inductor tools