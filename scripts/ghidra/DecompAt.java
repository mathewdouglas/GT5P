// Decompile the functions at the given addresses and write one .c file each.
//
// Headless use (see scripts/ghidra_decomp.cmd):
//   analyzeHeadless <projdir> <projname> -process EMAIN.ELF -noanalysis
//       -scriptPath scripts/ghidra -postScript DecompAt.java <outdir> <toc> <addr> [<addr> ...]
//
// The program is imported once with -noanalysis; a whole-program analysis of
// this executable takes far longer than reading a handful of functions needs.
// Each requested address is disassembled, made a function if it is not one,
// given the TOC value in r2 (the decompiler cannot resolve global references
// without it), and decompiled.
//
// The output is derived from the game binary. It belongs under analysis/,
// which is gitignored, and never in a tracked file.
//
//@category GT5P

import java.io.File;
import java.io.PrintWriter;
import java.math.BigInteger;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class DecompAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 3) {
            println("usage: DecompAt.java <outdir> <toc hex> <addr hex> [...]");
            return;
        }
        File outDir = new File(args[0]);
        outDir.mkdirs();
        BigInteger toc = new BigInteger(args[1].replace("0x", ""), 16);
        Register r2 = currentProgram.getRegister("r2");

        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        for (int i = 2; i < args.length; i++) {
            long a = Long.parseLong(args[i].replace("0x", ""), 16);
            Address addr = toAddr(a);
            Function fn = getFunctionAt(addr);
            if (fn == null) {
                new DisassembleCommand(addr, null, true).applyTo(currentProgram, monitor);
                fn = createFunction(addr, String.format("func_%08X", a));
            }
            if (fn == null) {
                println("no function at " + addr);
                continue;
            }
            if (r2 != null) {
                AddressSet body = new AddressSet(fn.getBody());
                for (ghidra.program.model.address.AddressRange r : body) {
                    currentProgram.getProgramContext().setValue(r2, r.getMinAddress(), r.getMaxAddress(), toc);
                }
            }
            DecompileResults res = dec.decompileFunction(fn, 120, monitor);
            File out = new File(outDir, String.format("func_%08X.c", a));
            try (PrintWriter pw = new PrintWriter(out)) {
                if (res != null && res.decompileCompleted()) {
                    pw.print(res.getDecompiledFunction().getC());
                } else {
                    pw.println("/* decompile failed: " + (res == null ? "null" : res.getErrorMessage()) + " */");
                }
            }
            println("wrote " + out.getPath() + " (" + fn.getBody().getNumAddresses() + " bytes)");
        }
        dec.dispose();
    }
}
